"""D02: Document publication must check dispatch ownership."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import ops_pilot.services.document_processing as processing
from ops_pilot.core.exceptions import DocumentProcessingError
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
)
from ops_pilot.models.document import DocumentStatus


@pytest.mark.anyio
async def test_stale_dispatch_cannot_start_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    old_dispatch = uuid.uuid4()
    new_dispatch = uuid.uuid4()

    job = BackgroundJob(
        id=job_id,
        organization_id=org_id,
        resource_id=doc_id,
        dispatch_id=new_dispatch,
        status=BackgroundJobStatus.PROCESSING,
        idempotency_key="test-dispatch",
    )

    session = AsyncMock()
    session.scalar.return_value = job

    # SQLAlchemy session.begin() is synchronous and returns
    # an asynchronous transaction context manager.
    session.begin = MagicMock()

    class Transaction:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return False

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    session.begin.return_value = Transaction()

    monkeypatch.setattr(
        processing,
        "async_session_factory",
        lambda: SessionContext(),
    )

    storage = AsyncMock()

    monkeypatch.setattr(
        processing,
        "S3Storage",
        lambda: storage,
    )

    with pytest.raises(
        RuntimeError,
        match="dispatch is no longer active",
    ):
        await processing.process_document_for_dispatch(
            organization_id=org_id,
            document_id=doc_id,
            job_id=job_id,
            dispatch_id=old_dispatch,
        )

    storage.download_file.assert_not_awaited()
    storage.upload_bytes.assert_not_awaited()


@pytest.mark.anyio
async def test_old_worker_cannot_publish_after_new_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old worker uploads, loses dispatch, then cannot publish."""

    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()
    job_id = uuid.uuid4()
    old_dispatch = uuid.uuid4()
    new_dispatch = uuid.uuid4()

    document = SimpleNamespace(
        id=document_id,
        organization_id=organization_id,
        storage_key="original/document.pdf",
        mime_type="application/pdf",
        status=DocumentStatus.PROCESSING,
        extracted_text_key=None,
        failure_reason=None,
    )

    active_job = BackgroundJob(
        id=job_id,
        organization_id=organization_id,
        resource_id=document_id,
        dispatch_id=old_dispatch,
        status=BackgroundJobStatus.PROCESSING,
        idempotency_key="race-test",
    )

    stale_job = BackgroundJob(
        id=job_id,
        organization_id=organization_id,
        resource_id=document_id,
        dispatch_id=new_dispatch,
        status=BackgroundJobStatus.PROCESSING,
        idempotency_key="race-test",
    )

    sessions = []

    @asynccontextmanager
    async def transaction():
        yield

    for job in (active_job, stale_job, stale_job):
        session = AsyncMock()
        session.scalar.return_value = job
        session.begin = MagicMock(return_value=transaction())
        sessions.append(session)

    session_iter = iter(sessions)

    @asynccontextmanager
    async def session_factory():
        session = next(session_iter)
        yield session

    monkeypatch.setattr(
        processing,
        "async_session_factory",
        session_factory,
    )

    monkeypatch.setattr(
        processing,
        "get_document",
        AsyncMock(return_value=document),
    )

    storage = SimpleNamespace(
        download_file=AsyncMock(return_value=b"fake-pdf"),
        upload_bytes=AsyncMock(),
    )

    monkeypatch.setattr(
        processing,
        "S3Storage",
        lambda: storage,
    )

    extracted = SimpleNamespace(
        pages=["Extracted page"],
        model_dump_json=lambda: '{"pages":["Extracted page"]}',
    )

    monkeypatch.setattr(
        processing,
        "extract_document_text",
        AsyncMock(return_value=extracted),
    )

    with pytest.raises(DocumentProcessingError):
        await processing.process_document_for_dispatch(
            organization_id=organization_id,
            document_id=document_id,
            job_id=job_id,
            dispatch_id=old_dispatch,
        )

    # Worker A successfully reached the upload stage.
    storage.download_file.assert_awaited_once()
    storage.upload_bytes.assert_awaited_once()

    uploaded_key = storage.upload_bytes.await_args.kwargs["key"]

    # Output belongs exclusively to the old dispatch.
    assert str(old_dispatch) in uploaded_key

    # A newer dispatch exists when Worker A attempts
    # to publish its uploaded result.
    assert len(sessions) == 3

    # The old worker could not change the document.
    assert document.extracted_text_key is None
    assert document.status == DocumentStatus.PROCESSING
    assert document.failure_reason is None
