import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.services.background_jobs import (
    mark_background_job_failed,
    mark_background_job_processing,
    mark_background_job_succeeded,
    set_background_job_event_id,
    update_background_job_progress,
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operation",
    [
        "processing",
        "succeeded",
        "failed",
        "progress",
        "event_id",
    ],
)
async def test_legacy_helpers_reject_dispatched_job(
    operation: str,
) -> None:
    job = BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        idempotency_key="legacy-guard-test",
        job_type=BackgroundJobType.DOCUMENT_PROCESSING,
        status=BackgroundJobStatus.QUEUED,
        dispatch_id=uuid.uuid4(),
    )

    session = AsyncMock()

    result = Mock()
    result.scalar_one_or_none.return_value = job
    session.execute.return_value = result

    async def invoke() -> None:
        if operation == "processing":
            await mark_background_job_processing(
                session=session,
                job=job,
                progress_percent=20,
            )
        elif operation == "succeeded":
            await mark_background_job_succeeded(
                session=session,
                job=job,
            )
        elif operation == "failed":
            await mark_background_job_failed(
                session=session,
                job=job,
                error_message="stale worker",
            )
        elif operation == "progress":
            await update_background_job_progress(
                session=session,
                job=job,
                progress_percent=40,
            )
        else:
            await set_background_job_event_id(
                session=session,
                job=job,
                event_id="stale-event",
            )

    with pytest.raises(
        RuntimeError,
        match="cannot modify a dispatched job",
    ):
        await invoke()

    session.commit.assert_not_awaited()
    assert job.status == BackgroundJobStatus.QUEUED


@pytest.mark.anyio
async def test_stale_in_memory_job_does_not_bypass_guard() -> None:
    job = BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        idempotency_key="stale-instance-test",
        job_type=BackgroundJobType.DOCUMENT_PROCESSING,
        status=BackgroundJobStatus.QUEUED,
        dispatch_id=None,
    )

    # Simulate a newer dispatch already in PostgreSQL
    # while the caller holds an older ORM object.
    current = BackgroundJob(
        id=job.id,
        organization_id=job.organization_id,
        resource_id=job.resource_id,
        idempotency_key=job.idempotency_key,
        job_type=job.job_type,
        status=BackgroundJobStatus.PROCESSING,
        dispatch_id=uuid.uuid4(),
    )

    session = AsyncMock()
    result = Mock()
    result.scalar_one_or_none.return_value = current
    session.execute.return_value = result

    with pytest.raises(RuntimeError):
        await mark_background_job_failed(
            session=session,
            job=job,
            error_message="old failure",
        )

    session.commit.assert_not_awaited()
    assert job.status == BackgroundJobStatus.QUEUED
