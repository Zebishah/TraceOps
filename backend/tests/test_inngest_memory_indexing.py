import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.inngest.functions.memory_indexing as module
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
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


def test_memory_failure_ignores_completed_job() -> None:
    dispatch_id = uuid.uuid4()

    job = BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=BackgroundJobType.MEMORY_INDEXING,
        status=BackgroundJobStatus.SUCCEEDED,
        resource_id=uuid.uuid4(),
        idempotency_key="completed-memory-job",
        dispatch_id=dispatch_id,
        progress_percent=100,
    )

    assert module._should_ignore_memory_failure(
        job=job,
        dispatch_id=dispatch_id,
    )


def test_memory_failure_ignores_previous_dispatch() -> None:
    job = BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=BackgroundJobType.MEMORY_INDEXING,
        status=BackgroundJobStatus.PROCESSING,
        resource_id=uuid.uuid4(),
        idempotency_key="retried-memory-job",
        dispatch_id=uuid.uuid4(),
        progress_percent=10,
    )

    assert module._should_ignore_memory_failure(
        job=job,
        dispatch_id=uuid.uuid4(),
    )


def test_memory_failure_allows_current_active_job() -> None:
    dispatch_id = uuid.uuid4()

    job = BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=BackgroundJobType.MEMORY_INDEXING,
        status=BackgroundJobStatus.PROCESSING,
        resource_id=uuid.uuid4(),
        idempotency_key="active-memory-job",
        dispatch_id=dispatch_id,
        progress_percent=10,
    )

    assert not module._should_ignore_memory_failure(
        job=job,
        dispatch_id=dispatch_id,
    )


def test_mark_memory_job_processing(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    job_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()

    job = BackgroundJob(
        id=job_id,
        organization_id=organization_id,
        created_by_user_id=None,
        job_type=BackgroundJobType.MEMORY_INDEXING,
        status=BackgroundJobStatus.QUEUED,
        resource_id=incident_id,
        idempotency_key=(f"memory-indexing:{incident_id}"),
        dispatch_id=dispatch_id,
        progress_percent=0,
    )

    session, _ = make_session()

    @asynccontextmanager
    async def fake_session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    async def fake_get_background_job(
        **kwargs: object,
    ) -> BackgroundJob:
        return job

    mark_processing = AsyncMock(return_value=True)

    monkeypatch.setattr(
        module,
        "async_session_factory",
        fake_session_factory,
    )

    monkeypatch.setattr(
        module,
        "get_background_job",
        fake_get_background_job,
    )

    monkeypatch.setattr(
        module,
        "update_job_for_dispatch",
        mark_processing,
    )

    result = asyncio.run(
        module._mark_memory_job_processing(
            organization_id=organization_id,
            job_id=job_id,
            incident_id=incident_id,
            dispatch_id=dispatch_id,
        )
    )

    assert result == {
        "already_succeeded": False,
    }

    mark_processing.assert_awaited_once_with(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        status=BackgroundJobStatus.PROCESSING,
        progress_percent=10,
    )


def test_memory_job_rejects_stale_dispatch() -> None:
    incident_id = uuid.uuid4()

    job = BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=BackgroundJobType.MEMORY_INDEXING,
        status=BackgroundJobStatus.QUEUED,
        resource_id=incident_id,
        idempotency_key="memory-test",
        dispatch_id=uuid.uuid4(),
        progress_percent=0,
    )

    stale_dispatch_id = uuid.uuid4()

    try:
        module._validate_memory_job(
            job=job,
            incident_id=incident_id,
            dispatch_id=stale_dispatch_id,
        )
    except RuntimeError as exc:
        assert str(exc) == ("Background job dispatch mismatch")
    else:
        raise AssertionError("Expected RuntimeError")
