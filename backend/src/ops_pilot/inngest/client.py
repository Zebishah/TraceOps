import inngest

from ops_pilot.core.config import get_settings

settings = get_settings()

inngest_client = inngest.Inngest(
    app_id="ops-pilot",
    event_key=settings.inngest_event_key,
    is_production=not settings.inngest_dev,
)
