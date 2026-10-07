import uuid

from ops_pilot.core.config import get_settings

REDIS_KEY_VERSION = "v1"


def build_incident_cache_key(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> str:
    settings = get_settings()

    return (
        f"{settings.redis_key_prefix}:"
        f"{REDIS_KEY_VERSION}:"
        f"cache:"
        f"org:{organization_id}:"
        f"incident:{incident_id}"
    )
