"""Real PostgreSQL tests for durable approval job claims.

Run ONLY against a dedicated, isolated test database.
"""

import asyncio
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

import ops_pilot.services.approval_resume_recovery as recovery
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
)
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.models.organization import Organization
from ops_pilot.models.user import User


@pytest.mark.asyncio
async def test_concurrent_resume_job_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.getenv("OPSPILOT_TEST_DATABASE_URL")

    if not url:
        pytest.skip("Set OPSPILOT_TEST_DATABASE_URL")

    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Requires a confirmed isolated test database")

    parsed = make_url(url)

    if parsed.get_backend_name() != "postgresql":
        pytest.fail("PostgreSQL is required")

    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
    )
    sessions = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        recovery,
        "async_session_factory",
        sessions,
    )

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    job_id = uuid.uuid4()
    suffix = uuid.uuid4().hex

    try:
        # Create synthetic parent records.
        async with sessions() as session:
            session.add(
                Organization(
                    id=org_id,
                    name="Resume concurrency test",
                    slug=f"resume-test-{suffix}",
                )
            )
            session.add(
                User(
                    id=user_id,
                    email=f"resume-{suffix}@example.com",
                    full_name="Synthetic Reviewer",
                    password_hash="synthetic",
                )
            )
            await session.flush()

            session.add(
                Incident(
                    id=incident_id,
                    organization_id=org_id,
                    created_by_user_id=user_id,
                    title="Resume lease test",
                    description="Synthetic approval recovery test",
                    status=IncidentStatus.AWAITING_APPROVAL,
                )
            )
            await session.flush()

            session.add(
                ApprovalRequest(
                    id=approval_id,
                    organization_id=org_id,
                    incident_id=incident_id,
                    workflow_thread_id=f"test-{approval_id}",
                    action_type=ApprovalActionType.REFUND_TRANSACTION,
                    action_payload={
                        "external_transaction_id": f"test-{suffix}",
                        "amount": "10.00",
                        "currency": "USD",
                    },
                    reason="Synthetic test only",
                    status=ApprovalStatus.APPROVED,
                    decided_by_user_id=user_id,
                    decided_at=datetime.now(UTC),
                )
            )
            await session.flush()

            session.add(
                ApprovalResumeJob(
                    id=job_id,
                    organization_id=org_id,
                    incident_id=incident_id,
                    approval_request_id=approval_id,
                    status=ApprovalResumeJobStatus.PENDING.value,
                )
            )
            await session.commit()

        # Two independent workers start simultaneously.
        start = asyncio.Event()

        async def competing_worker():
            await start.wait()
            return await recovery.claim_resume_jobs(limit=1)

        first_task = asyncio.create_task(competing_worker())
        second_task = asyncio.create_task(competing_worker())

        start.set()

        first, second = await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=20,
        )

        claims = [claim for batch in (first, second) for claim in batch if claim.id == job_id]

        # Exactly one worker owns the test job.
        assert len(claims) == 1

        winner = claims[0]

        # Verify the persisted claim state.
        async with sessions() as session:
            saved = await session.get(ApprovalResumeJob, job_id)

            assert saved is not None
            assert saved.status == (ApprovalResumeJobStatus.PROCESSING.value)
            assert saved.lease_token == winner.lease_token
            assert saved.attempts == 1

        # A different token cannot complete the job.
        stale = replace(
            winner,
            lease_token=uuid.uuid4(),
        )

        assert await recovery.complete_resume_job(job=stale) is False

        # The rightful owner may complete it.
        assert await recovery.complete_resume_job(job=winner) is True

        # Completed jobs must not be claimed again.
        further_claims = await recovery.claim_resume_jobs(limit=10)

        assert all(claim.id != job_id for claim in further_claims)

        async with sessions() as session:
            saved = await session.get(ApprovalResumeJob, job_id)

            assert saved is not None
            assert saved.status == (ApprovalResumeJobStatus.COMPLETED.value)
            assert saved.lease_token is None
            assert saved.completed_at is not None

    finally:
        # Clean up ONLY synthetic test-owned records.
        try:
            async with sessions() as session:
                await session.execute(delete(Organization).where(Organization.id == org_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
        finally:
            await engine.dispose()
