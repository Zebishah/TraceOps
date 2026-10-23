import uuid
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.background_job_dispatch as dispatch_module
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.services.background_jobs import (
    claim_background_job_send_lease,
    record_background_job_send_success,
)


def make_job() -> BackgroundJob:
    return BackgroundJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=BackgroundJobType.DOCUMENT_PROCESSING,
        status=BackgroundJobStatus.QUEUED,
        resource_id=uuid.uuid4(),
        idempotency_key="dispatch-lease-test",
        dispatch_id=uuid.uuid4(),
    )


def make_session(
    result_value: object | None,
) -> tuple[AsyncSession, AsyncMock]:
    session_mock = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalar_one_or_none.return_value = result_value
    session_mock.execute.return_value = result
    return cast(AsyncSession, session_mock), session_mock


@pytest.mark.asyncio
async def test_lease_claim_winner() -> None:
    job = make_job()
    token = uuid.uuid4()
    session, mocked = make_session(token)

    assert job.dispatch_id is not None

    result = await claim_background_job_send_lease(
        session=session,
        job=job,
        dispatch_id=job.dispatch_id,
    )

    assert result == token
    mocked.commit.assert_awaited_once()
    mocked.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_lease_claim_loser() -> None:
    job = make_job()
    session, mocked = make_session(None)

    assert job.dispatch_id is not None

    result = await claim_background_job_send_lease(
        session=session,
        job=job,
        dispatch_id=job.dispatch_id,
    )

    assert result is None
    mocked.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_sender_cannot_acknowledge() -> None:
    job = make_job()
    session, mocked = make_session(None)

    assert job.dispatch_id is not None

    recorded = await record_background_job_send_success(
        session=session,
        job=job,
        dispatch_id=job.dispatch_id,
        lease_token=uuid.uuid4(),
        event_id="evt_stale",
    )

    assert recorded is False
    mocked.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_current_sender_can_acknowledge() -> None:
    job = make_job()
    session, mocked = make_session(job.id)

    assert job.dispatch_id is not None

    recorded = await record_background_job_send_success(
        session=session,
        job=job,
        dispatch_id=job.dispatch_id,
        lease_token=uuid.uuid4(),
        event_id="evt_current",
    )

    assert recorded is True
    mocked.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_send_keeps_lease_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job()
    session, _ = make_session(None)
    assert job.dispatch_id is not None
    assert job.resource_id is not None

    claim = AsyncMock(return_value=uuid.uuid4())
    record = AsyncMock()

    monkeypatch.setattr(
        dispatch_module,
        "claim_background_job_send_lease",
        claim,
    )
    monkeypatch.setattr(
        dispatch_module,
        "record_background_job_send_success",
        record,
    )

    send = AsyncMock(
        side_effect=RuntimeError("Inngest timeout"),
    )
    monkeypatch.setattr(
        dispatch_module.inngest_client,
        "send",
        send,
    )

    with pytest.raises(RuntimeError, match="Inngest timeout"):
        await dispatch_module._send_background_job_event(
            session=session,
            job=job,
            dispatch_id=job.dispatch_id,
            event_name=dispatch_module.DOCUMENT_PROCESSING_EVENT,
            organization_id=job.organization_id,
            resource_id=job.resource_id,
        )

    claim.assert_awaited_once()
    send.assert_awaited_once()
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_losing_sender_does_not_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = make_job()
    session, _ = make_session(None)
    assert job.dispatch_id is not None
    assert job.resource_id is not None

    monkeypatch.setattr(
        dispatch_module,
        "claim_background_job_send_lease",
        AsyncMock(return_value=None),
    )

    send = AsyncMock()
    monkeypatch.setattr(
        dispatch_module.inngest_client,
        "send",
        send,
    )

    await dispatch_module._send_background_job_event(
        session=session,
        job=job,
        dispatch_id=job.dispatch_id,
        event_name=dispatch_module.DOCUMENT_PROCESSING_EVENT,
        organization_id=job.organization_id,
        resource_id=job.resource_id,
    )

    send.assert_not_awaited()
