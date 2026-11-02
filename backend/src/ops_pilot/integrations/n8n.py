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

    configured_base_url = settings.n8n_webhook_base_url
    configured_secret = settings.n8n_webhook_secret

    if configured_base_url is None or not configured_base_url.strip():
        raise RuntimeError("N8N_WEBHOOK_BASE_URL is not configured")

    if configured_secret is None or not configured_secret.strip():
        raise RuntimeError("N8N_WEBHOOK_SECRET is not configured")

    base_url = configured_base_url.strip().rstrip("/")
    webhook_secret = configured_secret
    path = webhook_path.strip().lstrip("/")

    if not path:
        raise ValueError("n8n webhook path must not be empty")

    async with httpx.AsyncClient(
        timeout=settings.n8n_timeout_seconds,
        follow_redirects=False,
    ) as client:

        async def send_request() -> httpx.Response:
            response = await client.post(
                f"{base_url}/{path}",
                json=event.model_dump(mode="json"),
                headers={
                    "X-OpsPilot-Webhook-Secret": webhook_secret,
                },
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

            # Validate inside the observed operation.
            # A non-success response must produce a failure log.
            response.raise_for_status()
            return response

        await observe_external_call(
            provider="n8n",
            operation="webhook",
            metadata={
                "webhook_path": path,
                "organization_id": str(event.organization_id),
            },
            call=send_request,
        )
