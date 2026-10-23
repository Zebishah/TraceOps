import uuid
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.services.background_jobs import (
    update_job_for_dispatch,
)


def make_job() -> BackgroundJob:
    resource_id = uuid.uuid4()

    return BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        job_type=BackgroundJobType.DOCUMENT_PROCESSING,
        resource_id=resource_id,
        dispatch_id=uuid.uuid4(),
        idempotency_key=f"document-processing:{resource_id}",
        status=BackgroundJobStatus.PROCESSING,
        progress_percent=60,
    )


def make_session(
    returned_id: uuid.UUID | None,
) -> tuple[AsyncSession, AsyncMock]:
    session_mock = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalar_one_or_none.return_value = returned_id

    session_mock.execute.return_value = result

    return cast(AsyncSession, session_mock), session_mock


@pytest.mark.asyncio
async def test_current_dispatch_can_complete() -> None:
    job = make_job()
    session, mocked = make_session(job.id)

    assert job.dispatch_id is not None

    updated = await update_job_for_dispatch(
        session=session,
        job=job,
        dispatch_id=job.dispatch_id,
        status=BackgroundJobStatus.SUCCEEDED,
        progress_percent=100,
    )

    assert updated is True
    mocked.commit.assert_awaited_once()
    mocked.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_dispatch_cannot_complete() -> None:
    job = make_job()
    session, mocked = make_session(None)

    updated = await update_job_for_dispatch(
        session=session,
        job=job,
        dispatch_id=uuid.uuid4(),
        status=BackgroundJobStatus.SUCCEEDED,
        progress_percent=100,
    )

    assert updated is False
    mocked.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_failure_message_is_truncated() -> None:
    job = make_job()
    session, mocked = make_session(job.id)

    assert job.dispatch_id is not None

    await update_job_for_dispatch(
        session=session,
        job=job,
        dispatch_id=job.dispatch_id,
        status=BackgroundJobStatus.FAILED,
        progress_percent=60,
        error_message="x" * 1500,
    )

    statement = mocked.execute.await_args.args[0]

    compiled = statement.compile(
        dialect=postgresql.dialect(),
    )

    assert "x" * 1000 in compiled.params.values()
    assert "x" * 1500 not in compiled.params.values()
