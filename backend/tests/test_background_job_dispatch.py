"""Dispatch idempotency tests for the lease-based dispatcher."""

import asyncio
import uuid
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.background_job_dispatch as module
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)


def make_session() -> AsyncSession:
    return cast(AsyncSession, AsyncMock(spec=AsyncSession))


def make_job(
    organization_id: uuid.UUID,
    resource_id: uuid.UUID,
    *,
    job_type: BackgroundJobType = BackgroundJobType.DOCUMENT_PROCESSING,
    status: BackgroundJobStatus = BackgroundJobStatus.QUEUED,
    dispatch_id: uuid.UUID | None = None,
    event_id: str | None = None,
) -> BackgroundJob:
    return BackgroundJob(
        id=uuid.uuid4(),
        organization_id=organization_id,
        created_by_user_id=None,
        job_type=job_type,
        status=status,
        resource_id=resource_id,
        idempotency_key=f"{job_type.value}:{resource_id}",
        dispatch_id=dispatch_id,
        inngest_event_id=event_id,
        progress_percent=0,
    )


def setup_mocks(
    monkeypatch: pytest.MonkeyPatch,
    job: BackgroundJob,
    *,
    claimed_dispatch_id: uuid.UUID | None = None,
    lease_token: uuid.UUID | None = None,
    returned_event_id: str = "evt_test",
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    monkeypatch.setattr(module, "get_document", AsyncMock())
    monkeypatch.setattr(module, "create_background_job", AsyncMock(return_value=job))
    prepare = AsyncMock(return_value=claimed_dispatch_id)
    claim = AsyncMock(return_value=lease_token)
    send = AsyncMock(return_value=[returned_event_id])
    record = AsyncMock(return_value=True)
    monkeypatch.setattr(module, "prepare_background_job_dispatch", prepare)
    monkeypatch.setattr(module, "claim_background_job_send_lease", claim)
    monkeypatch.setattr(module, "record_background_job_send_success", record)
    monkeypatch.setattr(module.inngest_client, "send", send)
    return prepare, claim, send, record


def test_enqueue_document_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    org, user, doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    job = make_job(org, doc)
    dispatch_id, lease_token = uuid.uuid4(), uuid.uuid4()
    prepare, claim, send, record = setup_mocks(
        monkeypatch, job, claimed_dispatch_id=dispatch_id, lease_token=lease_token
    )
    session = make_session()
    result = asyncio.run(
        module.enqueue_document_processing(
            session=session, organization_id=org, user_id=user, document_id=doc
        )
    )
    assert result is job
    prepare.assert_awaited_once_with(session=session, job=job)
    claim.assert_awaited_once_with(session=session, job=job, dispatch_id=dispatch_id)
    send.assert_awaited_once()
    event = send.await_args.args[0]
    assert event.id == str(dispatch_id)
    assert event.data["dispatch_id"] == str(dispatch_id)
    record.assert_awaited_once_with(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        lease_token=lease_token,
        event_id="evt_test",
    )


def test_existing_dispatched_job_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    org, user, doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    job = make_job(org, doc, dispatch_id=uuid.uuid4(), event_id="evt_existing")
    prepare, claim, send, record = setup_mocks(monkeypatch, job)
    result = asyncio.run(
        module.enqueue_document_processing(
            session=make_session(), organization_id=org, user_id=user, document_id=doc
        )
    )
    assert result is job
    prepare.assert_not_awaited()
    claim.assert_not_awaited()
    send.assert_not_awaited()
    record.assert_not_awaited()


def test_queued_job_without_event_id_resends_same_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, user, doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    dispatch_id, lease_token = uuid.uuid4(), uuid.uuid4()
    job = make_job(org, doc, dispatch_id=dispatch_id)
    prepare, claim, send, record = setup_mocks(
        monkeypatch, job, lease_token=lease_token, returned_event_id="evt_recovered"
    )
    session = make_session()
    result = asyncio.run(
        module.enqueue_document_processing(
            session=session, organization_id=org, user_id=user, document_id=doc
        )
    )
    assert result is job
    prepare.assert_not_awaited()
    claim.assert_awaited_once_with(session=session, job=job, dispatch_id=dispatch_id)
    send.assert_awaited_once()
    assert send.await_args.args[0].id == str(dispatch_id)
    record.assert_awaited_once_with(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        lease_token=lease_token,
        event_id="evt_recovered",
    )


def test_failed_document_job_is_redispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, user, doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    job = make_job(
        org, doc, status=BackgroundJobStatus.FAILED, dispatch_id=uuid.uuid4(), event_id="evt_old"
    )
    dispatch_id, lease_token = uuid.uuid4(), uuid.uuid4()
    prepare, claim, send, record = setup_mocks(
        monkeypatch,
        job,
        claimed_dispatch_id=dispatch_id,
        lease_token=lease_token,
        returned_event_id="evt_new",
    )
    session = make_session()
    result = asyncio.run(
        module.enqueue_document_processing(
            session=session, organization_id=org, user_id=user, document_id=doc
        )
    )
    assert result is job
    prepare.assert_awaited_once_with(session=session, job=job)
    claim.assert_awaited_once_with(session=session, job=job, dispatch_id=dispatch_id)
    send.assert_awaited_once()
    assert send.await_args.args[0].id == str(dispatch_id)
    record.assert_awaited_once_with(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        lease_token=lease_token,
        event_id="evt_new",
    )


def test_enqueue_memory_indexing(monkeypatch: pytest.MonkeyPatch) -> None:
    org, incident = uuid.uuid4(), uuid.uuid4()
    job = make_job(org, incident, job_type=BackgroundJobType.MEMORY_INDEXING)
    dispatch_id, lease_token = uuid.uuid4(), uuid.uuid4()
    prepare, claim, send, record = setup_mocks(
        monkeypatch,
        job,
        claimed_dispatch_id=dispatch_id,
        lease_token=lease_token,
        returned_event_id="evt_memory",
    )
    session = make_session()
    result = asyncio.run(
        module.enqueue_memory_indexing(session=session, organization_id=org, incident_id=incident)
    )
    assert result is job
    prepare.assert_awaited_once_with(session=session, job=job)
    claim.assert_awaited_once_with(session=session, job=job, dispatch_id=dispatch_id)
    send.assert_awaited_once()
    assert send.await_args.args[0].id == str(dispatch_id)
    record.assert_awaited_once_with(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        lease_token=lease_token,
        event_id="evt_memory",
    )


def test_lost_dispatch_claim_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    org, user, doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    job = make_job(org, doc)
    prepare, claim, send, record = setup_mocks(monkeypatch, job)
    result = asyncio.run(
        module.enqueue_document_processing(
            session=make_session(), organization_id=org, user_id=user, document_id=doc
        )
    )
    assert result is job
    prepare.assert_awaited_once()
    claim.assert_not_awaited()
    send.assert_not_awaited()
    record.assert_not_awaited()


def test_lease_not_acquired_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    org, user, doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    dispatch_id = uuid.uuid4()
    job = make_job(org, doc, dispatch_id=dispatch_id)
    prepare, claim, send, record = setup_mocks(monkeypatch, job)
    result = asyncio.run(
        module.enqueue_document_processing(
            session=make_session(), organization_id=org, user_id=user, document_id=doc
        )
    )
    assert result is job
    prepare.assert_not_awaited()
    claim.assert_awaited_once()
    send.assert_not_awaited()
    record.assert_not_awaited()
