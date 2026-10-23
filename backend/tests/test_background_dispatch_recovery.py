import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.background_dispatch_recovery as module
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)


@pytest.mark.asyncio
async def test_recovery_sends_existing_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()

    job = BackgroundJob(
        id=job_id,
        organization_id=organization_id,
        resource_id=resource_id,
        dispatch_id=dispatch_id,
        status=BackgroundJobStatus.QUEUED,
        job_type=BackgroundJobType.MEMORY_INDEXING,
        idempotency_key=f"memory-indexing:{resource_id}",
    )

    query_result = Mock()
    query_result.all.return_value = [
        (
            job_id,
            organization_id,
            resource_id,
            dispatch_id,
            BackgroundJobType.MEMORY_INDEXING,
        )
    ]

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result
    session.get.return_value = job

    @asynccontextmanager
    async def fake_factory() -> AsyncIterator[AsyncSession]:
        yield session

    send = AsyncMock()

    monkeypatch.setattr(
        module,
        "async_session_factory",
        fake_factory,
    )
    monkeypatch.setattr(
        module,
        "_send_background_job_event",
        send,
    )

    result = await module.recover_abandoned_dispatches()

    assert result.candidates == 1
    assert result.attempted == 1
    assert result.failed == 0

    send.assert_awaited_once_with(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        event_name=module.MEMORY_INDEXING_EVENT,
        organization_id=organization_id,
        resource_id=resource_id,
    )


@pytest.mark.asyncio
async def test_recovery_empty_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_result = Mock()
    query_result.all.return_value = []

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result

    @asynccontextmanager
    async def fake_factory() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setattr(
        module,
        "async_session_factory",
        fake_factory,
    )

    result = await module.recover_abandoned_dispatches()

    assert result.candidates == 0
    assert result.attempted == 0
    assert result.failed == 0
