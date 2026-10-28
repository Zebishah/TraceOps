import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
        occurred_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        payload=HighRiskIncidentPayload(
            incident_id=uuid.uuid4(),
            title="High-risk payment incident",
            priority="critical",
            category="payment",
        ),
    )


def test_retry_delay_is_bounded() -> None:
    assert outbox.retry_delay_seconds(1) == 30
    assert outbox.retry_delay_seconds(2) == 60
    assert outbox.retry_delay_seconds(3) == 120
    assert outbox.retry_delay_seconds(100) == 3600


@pytest.mark.anyio
async def test_event_is_persisted_before_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()
    operations: list[str] = []

    async def enqueue(**kwargs):
        assert kwargs["event"] is event
        operations.append("persisted")

    async def deliver(**kwargs):
        assert kwargs["delivery_id"] == event.event_id
        operations.append("delivered")
        return True

    monkeypatch.setattr(outbox, "enqueue_automation", enqueue)
    monkeypatch.setattr(outbox, "deliver_automation", deliver)

    result = await outbox.queue_and_attempt_automation(
        webhook_path="incident-high-risk",
        event=event,
    )

    assert result is True
    assert operations == ["persisted", "delivered"]


@pytest.mark.anyio
async def test_exhausted_lease_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_id = uuid.uuid4()

    captured = []

    @asynccontextmanager
    async def transaction():
        yield

    class FakeSession:
        def begin(self):
            return transaction()

        async def execute(self, statement):
            captured.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [expired_id]))

    @asynccontextmanager
    async def fake_session_factory():
        yield FakeSession()

    monkeypatch.setattr(
        outbox,
        "async_session_factory",
        fake_session_factory,
    )

    count = await outbox.expire_exhausted_delivery_leases()

    assert count == 1
    assert len(captured) == 1

    compiled = captured[0].compile()
    parameters = compiled.params

    assert "processing" in parameters.values()
    assert "dead" in parameters.values()
    assert outbox.MAX_DELIVERY_ATTEMPTS in parameters.values()


@pytest.mark.anyio
async def test_recovery_closes_exhausted_before_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = []

    async def fake_expire():
        operations.append("expire")
        return 2

    @asynccontextmanager
    async def fake_session_factory():
        class FakeSession:
            async def execute(self, statement):
                operations.append("select")
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

        yield FakeSession()

    monkeypatch.setattr(
        outbox,
        "expire_exhausted_delivery_leases",
        fake_expire,
    )

    monkeypatch.setattr(
        outbox,
        "async_session_factory",
        fake_session_factory,
    )

    result = await outbox.recover_automation_deliveries()

    assert operations == ["expire", "select"]
    assert result == {
        "examined": 0,
        "delivered": 0,
        "expired": 2,
    }


@pytest.mark.anyio
async def test_delivery_failure_is_finalized_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()
    token = uuid.uuid4()
    observed = {}

    async def claim(**kwargs):
        assert kwargs["delivery_id"] == event.event_id
        return (
            token,
            event.model_dump(mode="json"),
            "incident-high-risk",
        )

    async def finalize(**kwargs):
        observed.update(kwargs)
        return True

    send = AsyncMock(side_effect=ConnectionError("n8n unavailable"))

    monkeypatch.setattr(outbox, "claim_delivery", claim)
    monkeypatch.setattr(outbox, "finalize_delivery", finalize)
    monkeypatch.setattr(outbox, "send_n8n_event", send)

    result = await outbox.deliver_automation(delivery_id=event.event_id)

    assert result is False
    assert observed["delivery_id"] == event.event_id
    assert observed["token"] == token
    assert isinstance(observed["error"], ConnectionError)
    send.assert_awaited_once()


@pytest.mark.anyio
async def test_stale_worker_cannot_send_without_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send = AsyncMock()

    monkeypatch.setattr(
        outbox,
        "claim_delivery",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(outbox, "send_n8n_event", send)

    result = await outbox.deliver_automation(delivery_id=uuid.uuid4())

    assert result is False
    send.assert_not_awaited()


@pytest.mark.anyio
async def test_invalid_persisted_event_is_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery_id = uuid.uuid4()
    token = uuid.uuid4()
    finalized = {}

    monkeypatch.setattr(
        outbox,
        "claim_delivery",
        AsyncMock(
            return_value=(
                token,
                {"event_id": "not-a-uuid"},
                "incident-high-risk",
            )
        ),
    )

    async def finalize(**kwargs):
        finalized.update(kwargs)
        return True

    send = AsyncMock()

    monkeypatch.setattr(outbox, "finalize_delivery", finalize)
    monkeypatch.setattr(outbox, "send_n8n_event", send)

    assert await outbox.deliver_automation(delivery_id=delivery_id) is False

    send.assert_not_awaited()
    assert finalized["error"] is not None
