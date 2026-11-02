import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import ops_pilot.services.automation_outbox as outbox
from ops_pilot.schemas.automation_events import (
    AutomationEvent,
    HighRiskIncidentPayload,
)


def make_event() -> AutomationEvent:
    return AutomationEvent(
        event_id=uuid.uuid4(),
        event_type="incident.high_risk",
        organization_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        payload=HighRiskIncidentPayload(
            incident_id=uuid.uuid4(),
            title="Synthetic offline-delivery test",
            category="payment",
            priority="high",
        ),
    )


@pytest.mark.asyncio
async def test_paused_delivery_keeps_event_without_claiming(
    monkeypatch,
) -> None:
    event = make_event()
    enqueue = AsyncMock()
    claim = AsyncMock()
    send = AsyncMock()

    monkeypatch.setattr(
        outbox,
        "get_settings",
        lambda: SimpleNamespace(n8n_delivery_enabled=False),
    )
    monkeypatch.setattr(outbox, "enqueue_automation", enqueue)
    monkeypatch.setattr(outbox, "claim_delivery", claim)
    monkeypatch.setattr(outbox, "send_n8n_event", send)

    delivered = await outbox.queue_and_attempt_automation(
        webhook_path="incident-high-risk",
        event=event,
    )

    assert delivered is False
    enqueue.assert_awaited_once_with(
        webhook_path="incident-high-risk",
        event=event,
    )
    claim.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_paused_recovery_does_not_access_delivery_rows(
    monkeypatch,
) -> None:
    expire = AsyncMock()
    sessions = AsyncMock()

    monkeypatch.setattr(
        outbox,
        "get_settings",
        lambda: SimpleNamespace(n8n_delivery_enabled=False),
    )
    monkeypatch.setattr(
        outbox,
        "expire_exhausted_delivery_leases",
        expire,
    )
    monkeypatch.setattr(outbox, "async_session_factory", sessions)

    result = await outbox.recover_automation_deliveries()

    assert result == {
        "examined": 0,
        "delivered": 0,
        "expired": 0,
    }
    expire.assert_not_awaited()
    sessions.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_kind",
    ["connection", "timeout", "http"],
)
async def test_webhook_outage_is_recorded_without_escaping(
    monkeypatch,
    failure_kind: str,
) -> None:
    event = make_event()
    token = uuid.uuid4()
    request = httpx.Request(
        "POST",
        "https://n8n.example.com/webhook/incident-high-risk",
    )

    if failure_kind == "connection":
        failure = httpx.ConnectError(
            "Laptop offline",
            request=request,
        )
    elif failure_kind == "timeout":
        failure = httpx.ReadTimeout(
            "Webhook timed out",
            request=request,
        )
    else:
        failure = httpx.HTTPStatusError(
            "Service unavailable",
            request=request,
            response=httpx.Response(503, request=request),
        )

    monkeypatch.setattr(
        outbox,
        "get_settings",
        lambda: SimpleNamespace(
            n8n_delivery_enabled=True,
            n8n_timeout_seconds=1.0,
        ),
    )
    monkeypatch.setattr(
        outbox,
        "claim_delivery",
        AsyncMock(
            return_value=(
                token,
                event.model_dump(mode="json"),
                "incident-high-risk",
            )
        ),
    )

    finalize = AsyncMock(return_value=True)

    monkeypatch.setattr(
        outbox,
        "send_n8n_event",
        AsyncMock(side_effect=failure),
    )
    monkeypatch.setattr(outbox, "finalize_delivery", finalize)

    delivered = await outbox.deliver_automation(
        delivery_id=event.event_id,
    )

    assert delivered is False
    finalize.assert_awaited_once_with(
        delivery_id=event.event_id,
        token=token,
        error=failure,
    )
