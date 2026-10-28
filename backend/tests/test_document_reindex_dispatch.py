import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.background_job_dispatch as dispatch
from ops_pilot.models.background_job import BackgroundJobStatus
from ops_pilot.models.document import DocumentStatus


@pytest.mark.asyncio
async def test_ready_document_restarts_successful_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()
    user_id = uuid.uuid4()
    new_dispatch_id = uuid.uuid4()

    document = SimpleNamespace(
        status=DocumentStatus.READY,
        extracted_text_key="documents/extracted.json",
    )

    job = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=organization_id,
        resource_id=document_id,
        status=BackgroundJobStatus.SUCCEEDED,
        dispatch_id=uuid.uuid4(),
        inngest_event_id="old-event",
    )

    monkeypatch.setattr(
        dispatch,
        "get_document",
        AsyncMock(return_value=document),
    )

    monkeypatch.setattr(
        dispatch,
        "create_background_job",
        AsyncMock(return_value=job),
    )

    prepare = AsyncMock(return_value=new_dispatch_id)
    send = AsyncMock()

    monkeypatch.setattr(
        dispatch,
        "prepare_document_reindex_dispatch",
        prepare,
    )

    monkeypatch.setattr(
        dispatch,
        "_send_background_job_event",
        send,
    )

    session = AsyncMock()

    result = await dispatch.enqueue_document_reindex(
        session=session,
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
    )

    assert result is job

    prepare.assert_awaited_once_with(
        session=session,
        job=job,
        document_id=document_id,
    )

    send.assert_awaited_once()

    assert send.await_args.kwargs["dispatch_id"] == new_dispatch_id
    assert send.await_args.kwargs["resource_id"] == document_id


@pytest.mark.asyncio
async def test_active_reindex_is_not_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()

    document = SimpleNamespace(
        status=DocumentStatus.READY,
        extracted_text_key="documents/extracted.json",
    )

    job = SimpleNamespace(
        id=uuid.uuid4(),
        status=BackgroundJobStatus.PROCESSING,
        dispatch_id=uuid.uuid4(),
    )

    monkeypatch.setattr(
        dispatch,
        "get_document",
        AsyncMock(return_value=document),
    )

    monkeypatch.setattr(
        dispatch,
        "create_background_job",
        AsyncMock(return_value=job),
    )

    prepare = AsyncMock()
    send = AsyncMock()

    monkeypatch.setattr(
        dispatch,
        "prepare_document_reindex_dispatch",
        prepare,
    )

    monkeypatch.setattr(
        dispatch,
        "_send_background_job_event",
        send,
    )

    result = await dispatch.enqueue_document_reindex(
        session=AsyncMock(),
        organization_id=organization_id,
        user_id=uuid.uuid4(),
        document_id=document_id,
    )

    assert result is job
    prepare.assert_not_awaited()
    send.assert_not_awaited()
