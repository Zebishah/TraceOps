import asyncio
import uuid
from typing import cast
from unittest.mock import AsyncMock, Mock

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.services.background_jobs import (
    create_background_job,
    mark_background_job_failed,
    mark_background_job_processing,
    mark_background_job_succeeded,
)


def make_session() -> tuple[
    AsyncSession,
    AsyncMock,
]:
    session_mock = AsyncMock(
        spec=AsyncSession,
    )

    return (
        cast(
            AsyncSession,
            session_mock,
        ),
        session_mock,
    )


def test_create_background_job() -> None:
    session, session_mock = make_session()

    result = Mock()
    result.scalar_one_or_none.return_value = None

    cast(
        AsyncMock,
        session_mock.execute,
    ).return_value = result

    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    resource_id = uuid.uuid4()

    async def run() -> None:
        job = await create_background_job(
            session=session,
            organization_id=organization_id,
            created_by_user_id=user_id,
            job_type=(BackgroundJobType.DOCUMENT_PROCESSING),
            resource_id=resource_id,
            idempotency_key=(f"document-processing:{resource_id}"),
        )

        assert job.organization_id == organization_id

        assert job.job_type == BackgroundJobType.DOCUMENT_PROCESSING

        assert job.status == BackgroundJobStatus.QUEUED

    asyncio.run(run())

    session_mock.add.assert_called_once()

    cast(
        AsyncMock,
        session_mock.commit,
    ).assert_awaited_once()


def test_existing_idempotent_job_is_reused() -> None:
    session, session_mock = make_session()

    existing = BackgroundJob(
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=(BackgroundJobType.DOCUMENT_PROCESSING),
        resource_id=uuid.uuid4(),
        idempotency_key="existing-job",
    )

    result = Mock()
    result.scalar_one_or_none.return_value = existing

    cast(
        AsyncMock,
        session_mock.execute,
    ).return_value = result

    async def run() -> None:
        job = await create_background_job(
            session=session,
            organization_id=(existing.organization_id),
            created_by_user_id=None,
            job_type=(BackgroundJobType.DOCUMENT_PROCESSING),
            resource_id=cast(
                uuid.UUID,
                existing.resource_id,
            ),
            idempotency_key="existing-job",
        )

        assert job is existing

    asyncio.run(run())

    session_mock.add.assert_not_called()

    cast(
        AsyncMock,
        session_mock.commit,
    ).assert_not_awaited()


def test_background_job_state_transitions() -> None:
    session, session_mock = make_session()

    job = BackgroundJob(
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=(BackgroundJobType.DOCUMENT_PROCESSING),
        resource_id=uuid.uuid4(),
        idempotency_key="transition-job",
    )

    async def run() -> None:
        await mark_background_job_processing(
            session=session,
            job=job,
            progress_percent=20,
        )

        assert job.status == BackgroundJobStatus.PROCESSING
        assert job.progress_percent == 20
        assert job.started_at is not None

        await mark_background_job_succeeded(
            session=session,
            job=job,
        )

        assert job.status == BackgroundJobStatus.SUCCEEDED
        assert job.progress_percent == 100
        assert job.completed_at is not None

    asyncio.run(run())

    assert (
        cast(
            AsyncMock,
            session_mock.commit,
        ).await_count
        == 2
    )


def test_background_job_failure() -> None:
    session, _ = make_session()

    job = BackgroundJob(
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=(BackgroundJobType.DOCUMENT_PROCESSING),
        resource_id=uuid.uuid4(),
        idempotency_key="failed-job",
    )

    async def run() -> None:
        await mark_background_job_failed(
            session=session,
            job=job,
            error_message="Qdrant unavailable",
        )

        assert job.status == BackgroundJobStatus.FAILED

        assert job.error_message == "Qdrant unavailable"

        assert job.completed_at is not None

    asyncio.run(run())
