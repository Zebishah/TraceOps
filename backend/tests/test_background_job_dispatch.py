import asyncio
import uuid
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.background_job_dispatch as module
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


def make_job(
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    dispatch_id: uuid.UUID | None = None,
) -> BackgroundJob:
    return BackgroundJob(
        id=uuid.uuid4(),
        organization_id=organization_id,
        created_by_user_id=user_id,
        job_type=BackgroundJobType.DOCUMENT_PROCESSING,
        status=BackgroundJobStatus.QUEUED,
        resource_id=document_id,
        idempotency_key=(f"document-processing:{document_id}"),
        dispatch_id=dispatch_id,
        progress_percent=0,
    )


def test_enqueue_document_processing(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    document_id = uuid.uuid4()

    job = make_job(
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
    )

    session, _ = make_session()

    get_document_mock = AsyncMock()

    create_job_mock = AsyncMock(
        return_value=job,
    )

    set_event_id_mock = AsyncMock()

    dispatch_id = uuid.uuid4()

    prepare_mock = AsyncMock(
        return_value=dispatch_id,
    )

    send_mock = AsyncMock(
        return_value=["evt_test"],
    )

    monkeypatch.setattr(
        module,
        "get_document",
        get_document_mock,
    )

    monkeypatch.setattr(
        module,
        "create_background_job",
        create_job_mock,
    )

    monkeypatch.setattr(
        module,
        "prepare_background_job_dispatch",
        prepare_mock,
    )

    monkeypatch.setattr(
        module,
        "set_background_job_event_id",
        set_event_id_mock,
    )

    monkeypatch.setattr(
        module.inngest_client,
        "send",
        send_mock,
    )

    result = asyncio.run(
        module.enqueue_document_processing(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            document_id=document_id,
        )
    )

    assert result is job

    get_document_mock.assert_awaited_once_with(
        session=session,
        organization_id=organization_id,
        document_id=document_id,
    )

    create_job_mock.assert_awaited_once()

    prepare_mock.assert_awaited_once_with(
        session=session,
        job=job,
    )

    send_mock.assert_awaited_once()

    set_event_id_mock.assert_awaited_once_with(
        session=session,
        job=job,
        event_id="evt_test",
    )


def test_existing_dispatched_job_is_reused(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    document_id = uuid.uuid4()

    job = make_job(
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
        dispatch_id=uuid.uuid4(),
    )

    job.status = BackgroundJobStatus.QUEUED
    job.inngest_event_id = "evt_existing"

    session, _ = make_session()

    monkeypatch.setattr(
        module,
        "get_document",
        AsyncMock(),
    )

    monkeypatch.setattr(
        module,
        "create_background_job",
        AsyncMock(
            return_value=job,
        ),
    )

    send_mock = AsyncMock()

    monkeypatch.setattr(
        module.inngest_client,
        "send",
        send_mock,
    )

    result = asyncio.run(
        module.enqueue_document_processing(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            document_id=document_id,
        )
    )

    assert result is job

    send_mock.assert_not_awaited()


def test_queued_job_without_event_id_resends_same_dispatch(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    document_id = uuid.uuid4()
    dispatch_id = uuid.uuid4()

    job = make_job(
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
        dispatch_id=dispatch_id,
    )

    job.status = BackgroundJobStatus.QUEUED
    job.inngest_event_id = None

    session, _ = make_session()

    monkeypatch.setattr(
        module,
        "get_document",
        AsyncMock(),
    )

    monkeypatch.setattr(
        module,
        "create_background_job",
        AsyncMock(
            return_value=job,
        ),
    )

    prepare_mock = AsyncMock()

    monkeypatch.setattr(
        module,
        "prepare_background_job_dispatch",
        prepare_mock,
    )

    send_mock = AsyncMock(
        return_value=["evt_recovered"],
    )

    monkeypatch.setattr(
        module.inngest_client,
        "send",
        send_mock,
    )

    set_event_mock = AsyncMock()

    monkeypatch.setattr(
        module,
        "set_background_job_event_id",
        set_event_mock,
    )

    result = asyncio.run(
        module.enqueue_document_processing(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            document_id=document_id,
        )
    )

    assert result is job

    prepare_mock.assert_not_awaited()

    send_mock.assert_awaited_once()

    set_event_mock.assert_awaited_once_with(
        session=session,
        job=job,
        event_id="evt_recovered",
    )


def test_failed_document_job_is_redispatched(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    document_id = uuid.uuid4()

    job = make_job(
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
    )

    job.status = BackgroundJobStatus.FAILED
    job.inngest_event_id = "evt_old"

    new_dispatch_id = uuid.uuid4()

    session, _ = make_session()

    monkeypatch.setattr(
        module,
        "get_document",
        AsyncMock(),
    )

    monkeypatch.setattr(
        module,
        "create_background_job",
        AsyncMock(
            return_value=job,
        ),
    )

    prepare_mock = AsyncMock(
        return_value=new_dispatch_id,
    )

    monkeypatch.setattr(
        module,
        "prepare_background_job_dispatch",
        prepare_mock,
    )

    send_mock = AsyncMock(
        return_value=["evt_new"],
    )

    monkeypatch.setattr(
        module.inngest_client,
        "send",
        send_mock,
    )

    set_event_mock = AsyncMock()

    monkeypatch.setattr(
        module,
        "set_background_job_event_id",
        set_event_mock,
    )

    result = asyncio.run(
        module.enqueue_document_processing(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            document_id=document_id,
        )
    )

    assert result is job

    prepare_mock.assert_awaited_once_with(
        session=session,
        job=job,
    )

    send_mock.assert_awaited_once()

    set_event_mock.assert_awaited_once_with(
        session=session,
        job=job,
        event_id="evt_new",
    )
