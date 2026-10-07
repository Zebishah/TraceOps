from ops_pilot.core.config import get_settings


def get_default_cache_ttl_seconds() -> int:
    ttl_seconds = get_settings().redis_default_ttl_seconds

    if ttl_seconds <= 0:
        raise ValueError("Redis cache TTL must be greater than zero")

    return ttl_seconds
