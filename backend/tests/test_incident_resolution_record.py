import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from ops_pilot.models.incident import IncidentStatus
from ops_pilot.schemas.incidents import IncidentNoActionResolutionRequest
from ops_pilot.services import incident_resolution as service
from ops_pilot.services.incident_resolution_record import format_resolution_record

DETAILS = {
    "outcome": "no_issue_found",
    "reason": "  Reviewed payment records and found one settled charge.  ",
    "customer_message": "  We reviewed your payment records and found one settled charge.  ",
    "next_steps": "  Contact support if another settled charge appears.  ",
}


def test_detailed_request_and_record_preserve_reviewed_findings():
    request = IncidentNoActionResolutionRequest(**DETAILS)
    record = format_resolution_record(**request.model_dump())
    assert "Outcome: No issue found" in record
    assert request.reason == DETAILS["reason"].strip()
    assert "Customer message (recorded draft):" in record
    assert request.customer_message in record
    assert request.next_steps in record
    assert "customer delivery is not confirmed" in record


@pytest.mark.parametrize("field", ["reason", "customer_message", "next_steps"])
def test_whitespace_cannot_satisfy_detailed_closure(field):
    with pytest.raises(ValidationError):
        IncidentNoActionResolutionRequest(**{**DETAILS, field: " " * 20})


@pytest.mark.parametrize("field", ["outcome", "customer_message", "next_steps"])
def test_partial_closure_cannot_lose_customer_context(field):
    payload = {key: value for key, value in DETAILS.items() if key != field}
    with pytest.raises(ValidationError):
        IncidentNoActionResolutionRequest(**payload)


def test_legacy_reason_only_request_remains_compatible():
    request = IncidentNoActionResolutionRequest(reason="Reviewed and no correction is required.")
    assert format_resolution_record(**request.model_dump()) == request.reason


def test_unsupported_outcome_rejected_in_schema_and_service():
    with pytest.raises(ValidationError):
        IncidentNoActionResolutionRequest(**{**DETAILS, "outcome": "refund_executed"})
    with pytest.raises(ValueError):
        format_resolution_record(**{**DETAILS, "outcome": "refund_executed"})


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def test_detailed_record_saved_before_outbox_commit(monkeypatch):
    incident = SimpleNamespace(status=IncidentStatus.INVESTIGATING)
    session = AsyncMock()
    session.execute.side_effect = [Result(incident), Result(None), Result(None)]
    event = object()

    async def build_event(**kwargs):
        assert incident.status == IncidentStatus.RESOLVED
        assert "Customer message (recorded draft):" in incident.resolution_reason
        session.commit.assert_not_awaited()
        return event

    monkeypatch.setattr(service, "build_incident_resolved_event", build_event)
    enqueue = AsyncMock()
    monkeypatch.setattr(service, "enqueue_automation_in_session", enqueue)
    asyncio.run(
        service.resolve_incident_without_action(
            session=session,
            organization_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            resolved_by_user_id=uuid.uuid4(),
            **DETAILS,
        )
    )
    enqueue.assert_awaited_once_with(
        session=session,
        webhook_path="incident-resolved",
        event=event,
    )
    session.commit.assert_awaited_once()


def test_outbox_failure_rolls_back_closure(monkeypatch):
    session = AsyncMock()
    session.execute.side_effect = [
        Result(SimpleNamespace(status=IncidentStatus.INVESTIGATING)),
        Result(None),
        Result(None),
    ]
    monkeypatch.setattr(service, "build_incident_resolved_event", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        service,
        "enqueue_automation_in_session",
        AsyncMock(side_effect=RuntimeError("outbox unavailable")),
    )
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        asyncio.run(
            service.resolve_incident_without_action(
                session=session,
                organization_id=uuid.uuid4(),
                incident_id=uuid.uuid4(),
                resolved_by_user_id=uuid.uuid4(),
                **DETAILS,
            )
        )
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


def test_active_investigation_cannot_be_closed(monkeypatch):
    session = AsyncMock()
    session.execute.side_effect = [
        Result(SimpleNamespace(status=IncidentStatus.INVESTIGATING)),
        Result(None),
        Result(uuid.uuid4()),
    ]
    with pytest.raises(service.IncidentResolutionConflict, match="active investigation"):
        asyncio.run(
            service.resolve_incident_without_action(
                session=session,
                organization_id=uuid.uuid4(),
                incident_id=uuid.uuid4(),
                resolved_by_user_id=uuid.uuid4(),
                **DETAILS,
            )
        )
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.parametrize("has_customer", [False, True])
def test_resolution_event_carries_record_without_claiming_delivery(has_customer):
    from ops_pilot.services.automation_events import build_incident_resolved_event

    incident = SimpleNamespace(
        id=uuid.uuid4(),
        title="Payment concern",
        category="payment",
        priority=None,
        status=IncidentStatus.RESOLVED,
        subject_customer_id=uuid.uuid4() if has_customer else None,
        resolution_reason=format_resolution_record(**DETAILS),
    )
    session = AsyncMock()
    results = [Result(incident)]
    if has_customer:
        results.append(Result(SimpleNamespace(email="customer@example.com", full_name="Demo")))
    session.execute.side_effect = results
    event = asyncio.run(
        build_incident_resolved_event(
            session=session,
            organization_id=uuid.uuid4(),
            incident_id=incident.id,
        )
    )
    assert event.payload.resolution_reason == incident.resolution_reason
    assert "customer delivery is not confirmed" in event.payload.resolution_reason
    assert event.payload.customer_email == ("customer@example.com" if has_customer else None)
