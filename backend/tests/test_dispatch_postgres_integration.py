"""Real PostgreSQL concurrency tests for dispatch leases.

Requires OPSPILOT_TEST_DATABASE_URL.
Creates and cleans up its own temporary records.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.models.organization import Organization
from ops_pilot.services.background_jobs import (
    claim_background_job_send_lease,
    record_background_job_send_success,
)


@pytest.mark.asyncio
async def test_concurrent_dispatch_leases_on_real_postgres() -> None:
    database_url = os.environ.get("OPSPILOT_TEST_DATABASE_URL")

    if not database_url:
        pytest.skip("Set OPSPILOT_TEST_DATABASE_URL to run PostgreSQL test")

    parsed = make_url(database_url)

    if parsed.get_backend_name() != "postgresql":
        pytest.fail("This test requires PostgreSQL")

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )

    sessions = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    organization_id = uuid.uuid4()
    job_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()

    try:
        # STEP 1: Create the organization FIRST.
        async with sessions() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name="Dispatch concurrency test",
                    slug=f"dispatch-test-{organization_id.hex}",
                )
            )

            # This guarantees the parent exists in the database
            # before inserting the background job.
            await session.flush()

            session.add(
                BackgroundJob(
                    id=job_id,
                    organization_id=organization_id,
                    created_by_user_id=None,
                    job_type=BackgroundJobType.MEMORY_INDEXING,
                    status=BackgroundJobStatus.QUEUED,
                    resource_id=uuid.uuid4(),
                    idempotency_key=f"integration:{job_id}",
                    dispatch_id=dispatch_id,
                    progress_percent=0,
                )
            )

            await session.commit()

        # STEP 2: Simulate two simultaneous senders.
        async def claim_once() -> uuid.UUID | None:
            async with sessions() as session:
                job = await session.get(BackgroundJob, job_id)

                assert job is not None

                return await claim_background_job_send_lease(
                    session=session,
                    job=job,
                    dispatch_id=dispatch_id,
                )

        first, second = await asyncio.gather(
            claim_once(),
            claim_once(),
        )

        winners = [token for token in (first, second) if token is not None]

        # Exactly one sender can own the lease.
        assert len(winners) == 1

        old_token = winners[0]

        # STEP 3: An active lease blocks additional claims.
        assert await claim_once() is None

        # STEP 4: Simulate an expired lease.
        async with sessions() as session:
            await session.execute(
                update(BackgroundJob)
                .where(
                    BackgroundJob.id == job_id,
                    BackgroundJob.organization_id == organization_id,
                )
                .values(dispatch_lease_expires_at=(datetime.now(UTC) - timedelta(seconds=1)))
            )

            await session.commit()

        # STEP 5: A new sender should claim the expired lease.
        new_token = await claim_once()

        assert new_token is not None
        assert new_token != old_token

        # STEP 6: Previous sender must not acknowledge.
        async with sessions() as session:
            job = await session.get(BackgroundJob, job_id)

            assert job is not None

            recorded = await record_background_job_send_success(
                session=session,
                job=job,
                dispatch_id=dispatch_id,
                lease_token=old_token,
                event_id="evt_stale",
            )

            assert recorded is False

        # STEP 7: Current sender should acknowledge.
        async with sessions() as session:
            job = await session.get(BackgroundJob, job_id)

            assert job is not None

            recorded = await record_background_job_send_success(
                session=session,
                job=job,
                dispatch_id=dispatch_id,
                lease_token=new_token,
                event_id="evt_current",
            )

            assert recorded is True

        # STEP 8: Verify final database state.
        async with sessions() as session:
            result = await session.execute(
                select(BackgroundJob).where(
                    BackgroundJob.id == job_id,
                    BackgroundJob.organization_id == organization_id,
                )
            )

            job = result.scalar_one()

            assert job.inngest_event_id == "evt_current"
            assert job.dispatch_lease_token is None
            assert job.dispatch_lease_expires_at is None
            assert job.status == BackgroundJobStatus.QUEUED

    finally:
        # STEP 9: Remove only the records created by this test.
        try:
            async with sessions() as session:
                await session.execute(
                    delete(BackgroundJob).where(
                        BackgroundJob.id == job_id,
                        BackgroundJob.organization_id == organization_id,
                    )
                )

                await session.execute(
                    delete(Organization).where(
                        Organization.id == organization_id,
                    )
                )

                await session.commit()
        finally:
            await engine.dispose()
