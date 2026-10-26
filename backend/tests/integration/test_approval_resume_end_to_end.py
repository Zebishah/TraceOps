"""End-to-end rejected approval recovery using real PostgreSQL and LangGraph."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import ops_pilot.services.approval_resume_processor as processor
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
from ops_pilot.schemas.incident_actions import IncidentActionProposal
from ops_pilot.workflows.incident.checkpointing import (
    open_incident_checkpointer,
)
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)


@pytest.mark.asyncio
async def test_rejected_approval_completes_through_real_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("OPSPILOT_TEST_DATABASE_URL")

    if not database_url:
        pytest.skip("OPSPILOT_TEST_DATABASE_URL required")

    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Dedicated test database required")

    if os.getenv("DATABASE_URL") != database_url:
        pytest.fail("Application must use the isolated test database")

    if make_url(database_url).get_backend_name() != "postgresql":
        pytest.fail("PostgreSQL required")

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )

    sessions = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    # The actual worker and lease-management service must both
    # operate on the isolated test database.
    monkeypatch.setattr(
        processor,
        "async_session_factory",
        sessions,
    )
    monkeypatch.setattr(
        recovery,
        "async_session_factory",
        sessions,
    )

    suffix = uuid.uuid4().hex

    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    job_id = uuid.uuid4()

    thread_id = f"phase20-reject-e2e-{suffix}"
    now = datetime.now(UTC)

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    try:
        # Seed one entirely synthetic organization,
        # incident, rejected approval, and pending job.
        async with sessions() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name="Phase20 Recovery E2E Test",
                    slug=f"phase20-e2e-{suffix}",
                )
            )

            session.add(
                User(
                    id=user_id,
                    email=f"phase20-e2e-{suffix}@example.com",
                    full_name="Synthetic Reviewer",
                    password_hash="not-a-login",
                )
            )

            await session.flush()

            session.add(
                Incident(
                    id=incident_id,
                    organization_id=organization_id,
                    created_by_user_id=user_id,
                    title="Synthetic rejected refund",
                    description="Testing recovery of a rejected approval",
                    status=IncidentStatus.INVESTIGATING,
                )
            )
            # Persist the incident first because approval_requests
            # has a foreign key referencing incidents.id.
            await session.flush()
            session.add(
                ApprovalRequest(
                    id=approval_id,
                    organization_id=organization_id,
                    incident_id=incident_id,
                    workflow_thread_id=thread_id,
                    action_type=ApprovalActionType.REFUND_TRANSACTION,
                    action_payload={
                        "external_transaction_id": f"CHARGE-{suffix}",
                        "amount": "100.00",
                        "currency": "USD",
                    },
                    reason="Synthetic refund proposal",
                    status=ApprovalStatus.REJECTED,
                    decided_by_user_id=user_id,
                    decided_at=now,
                    decision_comment="Rejected by test reviewer",
                )
            )

            session.add(
                ApprovalResumeJob(
                    id=job_id,
                    organization_id=organization_id,
                    incident_id=incident_id,
                    approval_request_id=approval_id,
                    status=ApprovalResumeJobStatus.PENDING.value,
                    attempts=0,
                )
            )

            await session.commit()

        # Persist a real LangGraph approval interruption.
        proposal = IncidentActionProposal(
            requires_approval=True,
            action_type=ApprovalActionType.REFUND_TRANSACTION,
            external_transaction_id=f"CHARGE-{suffix}",
            amount="100.00",
            currency="USD",
            reason="Synthetic refund proposal",
        )

        async with open_incident_checkpointer() as checkpointer:
            graph = build_incident_investigation_graph(
                checkpointer=checkpointer,
            )

            await graph.aupdate_state(
                config,
                {
                    "organization_id": organization_id,
                    "incident_id": incident_id,
                    "workflow_thread_id": thread_id,
                    "approval_request_id": approval_id,
                    "proposed_action": proposal,
                },
                as_node="create_approval",
            )

            await graph.ainvoke(
                None,
                config=config,
            )

            before = await graph.aget_state(config)

            assert any(
                task.name == "approval_gate" and bool(task.interrupts) for task in before.tasks
            )

        # Execute the REAL worker rather than a mocked
        # process_claimed_resume_job function.
        result = await processor.run_approval_resume_sweep()

        assert result.claimed == 1
        assert result.completed == 1
        assert result.failed == 0

        # Verify all persisted database results.
        async with sessions() as session:
            job = await session.get(ApprovalResumeJob, job_id)
            approval = await session.get(ApprovalRequest, approval_id)
            incident = await session.get(Incident, incident_id)

            assert job is not None
            assert approval is not None
            assert incident is not None

            assert job.status == ApprovalResumeJobStatus.COMPLETED.value
            assert job.completed_at is not None
            assert job.lease_token is None

            assert approval.status == ApprovalStatus.REJECTED
            assert incident.status == IncidentStatus.INVESTIGATING

            await session.rollback()

        # Verify the actual terminal LangGraph checkpoint.
        async with open_incident_checkpointer() as checkpointer:
            graph = build_incident_investigation_graph(
                checkpointer=checkpointer,
            )

            after = await graph.aget_state(config)

            assert not after.next
            assert not after.tasks

            decision = after.values["approval_decision"]

            approved = decision["approved"] if isinstance(decision, dict) else decision.approved

            assert approved is False

        # An already completed job must not be claimed again.
        claimed_again = await recovery.claim_resume_jobs(limit=1)

        assert claimed_again == []

    finally:
        # Delete only this test's checkpoint thread.
        try:
            async with sessions() as session:
                for table in (
                    "checkpoint_writes",
                    "checkpoint_blobs",
                    "checkpoints",
                ):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE thread_id = :thread_id"),
                        {"thread_id": thread_id},
                    )

                await session.commit()

        finally:
            try:
                async with sessions() as session:
                    await session.execute(
                        delete(Organization).where(Organization.id == organization_id)
                    )
                    await session.execute(delete(User).where(User.id == user_id))
                    await session.commit()
            finally:
                await engine.dispose()
