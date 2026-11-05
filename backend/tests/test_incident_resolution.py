import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.incident_resolution as resolution_service
from ops_pilot.models.approval import ApprovalStatus
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.services.incident_resolution import (
    IncidentResolutionConflict,
    IncidentResolutionNotFound,
    resolve_incident_without_action,
)


class FakeResult:
    def __init__(self, value: object | None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def make_session(*values):
    session = AsyncMock()
    session.execute.side_effect = [FakeResult(value) for value in values] + [FakeResult(None)]
    session.refresh = AsyncMock()
    return session


def run_resolution(session, reason="Verified no refund is required."):
    return asyncio.run(
        resolve_incident_without_action(
            session=session,
            organization_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            resolved_by_user_id=uuid.uuid4(),
            reason=reason,
        )
    )


def test_resolution_succeeds_when_no_active_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = SimpleNamespace(
        status=IncidentStatus.INVESTIGATING,
        resolved_by_user_id=None,
        resolution_reason=None,
        resolved_at=None,
    )

    session = make_session(incident, None)

    event = object()
    build_event = AsyncMock(return_value=event)
    enqueue_event = AsyncMock()

    monkeypatch.setattr(
        resolution_service,
        "build_incident_resolved_event",
        build_event,
    )
    monkeypatch.setattr(
        resolution_service,
        "enqueue_automation_in_session",
        enqueue_event,
    )

    result = run_resolution(session)

    assert result is incident
    assert result.status == IncidentStatus.RESOLVED
    assert result.resolved_by_user_id is not None
    assert result.resolution_reason == "Verified no refund is required."
    assert result.resolved_at is not None

    session.flush.assert_awaited_once()
    build_event.assert_awaited_once()

    event_call = build_event.await_args
    assert event_call is not None
    assert event_call.kwargs["session"] is session
    assert isinstance(event_call.kwargs["organization_id"], uuid.UUID)
    assert isinstance(event_call.kwargs["incident_id"], uuid.UUID)

    enqueue_event.assert_awaited_once_with(
        session=session,
        webhook_path="incident-resolved",
        event=event,
    )

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    session.refresh.assert_awaited_once_with(incident)


@pytest.mark.parametrize(
    "status",
    [
        IncidentStatus.NEW,
        IncidentStatus.AWAITING_APPROVAL,
        IncidentStatus.RESOLVED,
        IncidentStatus.FAILED,
    ],
)
def test_resolution_rejects_invalid_incident_status(status):
    incident = SimpleNamespace(status=status)
    session = make_session(incident)

    with pytest.raises(IncidentResolutionConflict):
        run_resolution(session)

    session.commit.assert_not_awaited()


def test_resolution_rejects_missing_incident():
    session = make_session(None)

    with pytest.raises(IncidentResolutionNotFound):
        run_resolution(session)

    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "approval_status",
    [
        ApprovalStatus.PENDING,
        ApprovalStatus.APPROVED,
        ApprovalStatus.EXECUTED,
    ],
)
def test_resolution_rejects_active_approval(approval_status):
    incident = SimpleNamespace(
        status=IncidentStatus.INVESTIGATING,
    )

    # The service returns an approval ID when any
    # blocking approval exists.
    session = make_session(incident, uuid.uuid4())

    with pytest.raises(IncidentResolutionConflict):
        run_resolution(session)

    session.commit.assert_not_awaited()


def test_resolution_requires_explanation():
    session = make_session()

    with pytest.raises(ValueError):
        run_resolution(session, reason="short")

    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()

