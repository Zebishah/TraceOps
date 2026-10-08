import httpx

from ops_pilot.core.config import get_settings
from ops_pilot.schemas.automation_events import AutomationEvent


async def send_n8n_event(
    *,
    webhook_path: str,
    event: AutomationEvent,
) -> None:
    settings = get_settings()

    if settings.n8n_webhook_base_url is None:
        raise RuntimeError("N8N_WEBHOOK_BASE_URL is not configured")

    base_url = settings.n8n_webhook_base_url.rstrip("/")
    path = webhook_path.lstrip("/")

    async with httpx.AsyncClient(
        timeout=settings.n8n_timeout_seconds,
    ) as client:
        response = await client.post(
            f"{base_url}/{path}",
            json=event.model_dump(mode="json"),
        )

        response.raise_for_status()
