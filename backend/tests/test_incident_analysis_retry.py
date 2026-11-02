import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.incident_background as service
from ops_pilot.models.background_job import (
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.models.incident import IncidentStatus


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_status",
    [
        BackgroundJobStatus.QUEUED,
        BackgroundJobStatus.PROCESSING,
        BackgroundJobStatus.SUCCEEDED,
    ],
)
async def test_retry_rejects_non_failed_jobs(
    monkeypatch: pytest.MonkeyPatch,
    job_status: BackgroundJobStatus,
) -> None:
    incident_id = uuid.uuid4()
    job = SimpleNamespace(
        job_type=BackgroundJobType.INCIDENT_ANALYSIS,
        resource_id=incident_id,
        status=job_status,
    )
    prepare = AsyncMock()
    send = AsyncMock()

    monkeypatch.setattr(service, "get_background_job", AsyncMock(return_value=job))
    monkeypatch.setattr(service, "prepare_background_job_dispatch", prepare)
    monkeypatch.setattr(service, "_send_background_job_event", send)

    with pytest.raises(service.InvestigationRetryConflict):
        await service.retry_incident_analysis(
            session=cast(AsyncSession, AsyncMock()),
            organization_id=uuid.uuid4(),
            incident_id=incident_id,
            job_id=uuid.uuid4(),
            requested_by_user_id=uuid.uuid4(),
        )

    prepare.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_rejects_wrong_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(
        job_type=BackgroundJobType.INCIDENT_ANALYSIS,
        resource_id=uuid.uuid4(),
        status=BackgroundJobStatus.FAILED,
    )
    prepare = AsyncMock()

    monkeypatch.setattr(service, "get_background_job", AsyncMock(return_value=job))
    monkeypatch.setattr(service, "prepare_background_job_dispatch", prepare)

    with pytest.raises(service.InvestigationRetryNotFound):
        await service.retry_incident_analysis(
            session=cast(AsyncSession, AsyncMock()),
            organization_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            requested_by_user_id=uuid.uuid4(),
        )

    prepare.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "incident_status",
    [
        IncidentStatus.AWAITING_APPROVAL,
        IncidentStatus.RESOLVED,
        IncidentStatus.FAILED,
    ],
)
async def test_retry_does_not_restart_approval_or_closed_workflows(
    monkeypatch: pytest.MonkeyPatch,
    incident_status: IncidentStatus,
) -> None:
    incident_id = uuid.uuid4()
    job = SimpleNamespace(
        job_type=BackgroundJobType.INCIDENT_ANALYSIS,
        resource_id=incident_id,
        status=BackgroundJobStatus.FAILED,
    )
    prepare = AsyncMock()

    monkeypatch.setattr(service, "get_background_job", AsyncMock(return_value=job))
    monkeypatch.setattr(
        service,
        "get_incident",
        AsyncMock(return_value=SimpleNamespace(status=incident_status)),
    )
    monkeypatch.setattr(service, "prepare_background_job_dispatch", prepare)

    with pytest.raises(service.InvestigationRetryConflict):
        await service.retry_incident_analysis(
            session=cast(AsyncSession, AsyncMock()),
            organization_id=uuid.uuid4(),
            incident_id=incident_id,
            job_id=uuid.uuid4(),
            requested_by_user_id=uuid.uuid4(),
        )

    prepare.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("claim_won", [True, False])
async def test_retry_sends_only_after_winning_dispatch_transition(
    monkeypatch: pytest.MonkeyPatch,
    claim_won: bool,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    job_id = uuid.uuid4()
    new_dispatch_id = uuid.uuid4()
    session = cast(AsyncSession, AsyncMock())

    job = SimpleNamespace(
        id=job_id,
        job_type=BackgroundJobType.INCIDENT_ANALYSIS,
        resource_id=incident_id,
        status=BackgroundJobStatus.FAILED,
        dispatch_id=uuid.uuid4(),
    )

    monkeypatch.setattr(service, "get_background_job", AsyncMock(return_value=job))
    monkeypatch.setattr(
        service,
        "get_incident",
        AsyncMock(return_value=SimpleNamespace(status=IncidentStatus.INVESTIGATING)),
    )
    prepare = AsyncMock(return_value=new_dispatch_id if claim_won else None)
    send = AsyncMock()

    monkeypatch.setattr(service, "prepare_background_job_dispatch", prepare)
    monkeypatch.setattr(service, "_send_background_job_event", send)

    async def retry() -> object:
        return await service.retry_incident_analysis(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            job_id=job_id,
            requested_by_user_id=uuid.uuid4(),
        )

    if claim_won:
        result = await retry()
        assert result is job
        send.assert_awaited_once_with(
            session=session,
            job=job,
            dispatch_id=new_dispatch_id,
            event_name=service.INCIDENT_ANALYSIS_EVENT,
            organization_id=organization_id,
            resource_id=incident_id,
        )
    else:
        with pytest.raises(service.InvestigationRetryConflict):
            await retry()

        send.assert_not_awaited()
