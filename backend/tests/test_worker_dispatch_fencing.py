import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.inngest.functions.document_processing as document_module
import ops_pilot.inngest.functions.memory_indexing as memory_module
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)


def make_job(
    job_type: BackgroundJobType,
) -> BackgroundJob:
    resource_id = uuid.uuid4()

    return BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        resource_id=resource_id,
        job_type=job_type,
        status=BackgroundJobStatus.PROCESSING,
        dispatch_id=uuid.uuid4(),
        progress_percent=60,
        idempotency_key=f"{job_type.value}:{resource_id}",
    )


def setup_session(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    job: BackgroundJob,
) -> AsyncMock:
    session_mock = AsyncMock(spec=AsyncSession)
    session = cast(AsyncSession, session_mock)

    @asynccontextmanager
    async def fake_factory() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setattr(
        module,
        "async_session_factory",
        fake_factory,
    )
    monkeypatch.setattr(
        module,
        "get_background_job",
        AsyncMock(return_value=job),
    )

    return session_mock


@pytest.mark.asyncio
async def test_stale_document_cannot_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job(BackgroundJobType.DOCUMENT_PROCESSING)

    setup_session(monkeypatch, document_module, job)

    protected_update = AsyncMock(return_value=False)
    monkeypatch.setattr(
        document_module,
        "update_job_for_dispatch",
        protected_update,
    )

    assert job.dispatch_id is not None

    with pytest.raises(RuntimeError, match="Stale dispatch"):
        await document_module._mark_job_succeeded(
            organization_id=job.organization_id,
            job_id=job.id,
            dispatch_id=job.dispatch_id,
        )

    protected_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_memory_cannot_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job(BackgroundJobType.MEMORY_INDEXING)

    setup_session(monkeypatch, memory_module, job)

    protected_update = AsyncMock(return_value=False)
    monkeypatch.setattr(
        memory_module,
        "update_job_for_dispatch",
        protected_update,
    )

    assert job.dispatch_id is not None
    assert job.resource_id is not None

    with pytest.raises(RuntimeError, match="Stale dispatch"):
        await memory_module._mark_memory_job_succeeded(
            organization_id=job.organization_id,
            job_id=job.id,
            incident_id=job.resource_id,
            dispatch_id=job.dispatch_id,
        )

    protected_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_document_dispatch_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job(BackgroundJobType.DOCUMENT_PROCESSING)

    setup_session(monkeypatch, document_module, job)

    protected_update = AsyncMock()
    monkeypatch.setattr(
        document_module,
        "update_job_for_dispatch",
        protected_update,
    )

    with pytest.raises(
        RuntimeError,
        match="dispatch mismatch",
    ):
        await document_module._mark_job_processing(
            organization_id=job.organization_id,
            job_id=job.id,
            document_id=cast(uuid.UUID, job.resource_id),
            dispatch_id=uuid.uuid4(),
        )

    protected_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_memory_dispatch_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job(BackgroundJobType.MEMORY_INDEXING)

    setup_session(monkeypatch, memory_module, job)

    protected_update = AsyncMock()
    monkeypatch.setattr(
        memory_module,
        "update_job_for_dispatch",
        protected_update,
    )

    with pytest.raises(
        RuntimeError,
        match="dispatch mismatch",
    ):
        await memory_module._mark_memory_job_processing(
            organization_id=job.organization_id,
            job_id=job.id,
            incident_id=cast(uuid.UUID, job.resource_id),
            dispatch_id=uuid.uuid4(),
        )

    protected_update.assert_not_awaited()
