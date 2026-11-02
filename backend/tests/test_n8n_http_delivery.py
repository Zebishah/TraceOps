import logging
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

import ops_pilot.integrations.n8n as integration
from ops_pilot.schemas.automation_events import (
    AutomationEvent,
    HighRiskIncidentPayload,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 404, 401, 500])
async def test_n8n_delivery_checks_http_status_inside_observation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
) -> None:
    event = AutomationEvent(
        event_id=uuid.uuid4(),
        event_type="incident.high_risk",
        organization_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        payload=HighRiskIncidentPayload(
            incident_id=uuid.uuid4(),
            title="Synthetic notification test",
            category="payment",
            priority="high",
        ),
    )

    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status_code,
            json={"status": "test"},
        )

    real_async_client = httpx.AsyncClient

    def make_client(
        *,
        timeout: float,
        follow_redirects: bool,
    ) -> httpx.AsyncClient:
        assert follow_redirects is False

        return real_async_client(
            transport=httpx.MockTransport(handle),
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(
        integration,
        "get_settings",
        lambda: SimpleNamespace(
            n8n_webhook_base_url="https://n8n.example.com/webhook/",
            n8n_webhook_secret="test-secret",
            n8n_timeout_seconds=5.0,
        ),
    )
    monkeypatch.setattr(
        integration.httpx,
        "AsyncClient",
        make_client,
    )

    with caplog.at_level(logging.INFO):
        if status_code == 200:
            await integration.send_n8n_event(
                webhook_path="incident-high-risk",
                event=event,
            )
        else:
            with pytest.raises(httpx.HTTPStatusError):
                await integration.send_n8n_event(
                    webhook_path="incident-high-risk",
                    event=event,
                )

    assert len(requests) == 1
    assert str(requests[0].url) == ("https://n8n.example.com/webhook/incident-high-risk")
    assert requests[0].headers["X-OpsPilot-Webhook-Secret"] == "test-secret"

    observation_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ops_pilot.integrations.observability"
    ]

    if status_code == 200:
        assert "external_call_succeeded" in observation_messages
        assert "external_call_failed" not in observation_messages
    else:
        assert "external_call_failed" in observation_messages
        assert "external_call_succeeded" not in observation_messages
