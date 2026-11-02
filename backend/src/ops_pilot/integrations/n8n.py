import logging

import httpx

from ops_pilot.core.config import get_settings
from ops_pilot.integrations.observability import observe_external_call
from ops_pilot.schemas.automation_events import AutomationEvent

logger = logging.getLogger(__name__)


async def send_n8n_event(
    *,
    webhook_path: str,
    event: AutomationEvent,
) -> None:
    settings = get_settings()

    if settings.n8n_webhook_base_url is None:
        raise RuntimeError("N8N_WEBHOOK_BASE_URL is not configured")

    if settings.n8n_webhook_secret is None:
        raise RuntimeError("N8N_WEBHOOK_SECRET is not configured")
    webhook_secret = settings.n8n_webhook_secret
    base_url = settings.n8n_webhook_base_url.rstrip("/")
    path = webhook_path.lstrip("/")

    async with httpx.AsyncClient(
        timeout=settings.n8n_timeout_seconds,
    ) as client:

        async def send_request() -> httpx.Response:
            return await client.post(
                f"{base_url}/{path}",
                json=event.model_dump(mode="json"),
                headers={
                    "X-OpsPilot-Webhook-Secret": webhook_secret,
                },
            )

        response = await observe_external_call(
            provider="n8n",
            operation="webhook",
            metadata={
                "webhook_path": path,
            },
            call=send_request,
        )

        logger.info(
            "external_http_response",
            extra={
                "provider": "n8n",
                "operation": "webhook",
                "status_code": response.status_code,
                "webhook_path": path,
            },
        )

        response.raise_for_status()
