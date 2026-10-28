"""D03: Stale dispatches cannot index or publish document generations."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.document_indexing as indexing
from ops_pilot.core.exceptions import DocumentProcessingError
from ops_pilot.models.background_job import BackgroundJobStatus


@pytest.mark.anyio
async def test_stale_dispatch_cannot_modify_qdrant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()
    job_id = uuid.uuid4()

    old_dispatch = uuid.uuid4()
    new_dispatch = uuid.uuid4()

    job = SimpleNamespace(
        dispatch_id=new_dispatch,
        status=BackgroundJobStatus.PROCESSING,
    )

    guard_session = AsyncMock()
    guard_session.scalar.return_value = job

    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def session_factory():
        guard_session.begin = lambda: transaction()
        yield guard_session

    monkeypatch.setattr(
        indexing,
        "async_session_factory",
        session_factory,
    )

    perform_indexing = AsyncMock(return_value=3)

    monkeypatch.setattr(
        indexing,
        "_index_document_unlocked",
        perform_indexing,
    )

    with pytest.raises(
        DocumentProcessingError,
        match="dispatch is no longer active",
    ):
        await indexing.index_document(
            session=AsyncMock(),
            organization_id=organization_id,
            document_id=document_id,
            job_id=job_id,
            dispatch_id=old_dispatch,
        )

    # Stale workers must never start Qdrant indexing.
    perform_indexing.assert_not_awaited()

    # The guard should only check the job.
    guard_session.scalar.assert_awaited_once()


@pytest.mark.anyio
async def test_active_dispatch_runs_indexing_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()
    job_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()

    job = SimpleNamespace(
        dispatch_id=dispatch_id,
        status=BackgroundJobStatus.PROCESSING,
    )

    # The document generation begins unpublished.
    document = SimpleNamespace(
        id=document_id,
        organization_id=organization_id,
        active_index_generation=None,
    )

    guard_session = AsyncMock()

    # First scalar() loads the background job.
    # Second scalar() loads the document.
    guard_session.scalar.side_effect = [
        job,
        document,
    ]

    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def session_factory():
        guard_session.begin = lambda: transaction()
        yield guard_session

    monkeypatch.setattr(
        indexing,
        "async_session_factory",
        session_factory,
    )

    perform_indexing = AsyncMock(return_value=3)

    monkeypatch.setattr(
        indexing,
        "_index_document_unlocked",
        perform_indexing,
    )

    document_session = AsyncMock()

    result = await indexing.index_document(
        session=document_session,
        organization_id=organization_id,
        document_id=document_id,
        job_id=job_id,
        dispatch_id=dispatch_id,
    )

    assert result == 3

    # Indexing must happen exactly once, using this dispatch.
    perform_indexing.assert_awaited_once_with(
        session=document_session,
        organization_id=organization_id,
        document_id=document_id,
        generation_id=dispatch_id,
    )

    # The correct generation must be published.
    assert document.active_index_generation == dispatch_id

    # One query for the job and one for the document.
    assert guard_session.scalar.await_count == 2


@pytest.mark.anyio
async def test_index_rejects_incomplete_dispatch_identity() -> None:
    with pytest.raises(
        ValueError,
        match="must be supplied together",
    ):
        await indexing.index_document(
            session=AsyncMock(),
            organization_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
        )
