import json
import uuid

from ops_pilot.cache.keys import (
    build_incident_cache_key,
)
from ops_pilot.cache.redis import (
    get_redis_client,
)
from ops_pilot.cache.ttl import (
    get_default_cache_ttl_seconds,
)


async def set_cache_json(
    *,
    key: str,
    value: dict[str, object],
    ttl_seconds: int | None = None,
) -> None:
    redis = get_redis_client()

    ttl = ttl_seconds if ttl_seconds is not None else get_default_cache_ttl_seconds()

    if ttl <= 0:
        raise ValueError("Redis cache TTL must be greater than zero")

    serialized = json.dumps(
        value,
        separators=(",", ":"),
        default=str,
    )

    await redis.set(
        key,
        serialized,
        ex=ttl,
    )


async def get_cache_json(
    *,
    key: str,
) -> dict[str, object] | None:
    redis = get_redis_client()

    cached = await redis.get(
        key,
    )

    if cached is None:
        return None

    try:
        parsed = json.loads(
            cached,
        )
    except json.JSONDecodeError:
        await redis.delete(
            key,
        )

        return None

    if not isinstance(
        parsed,
        dict,
    ):
        await redis.delete(
            key,
        )

        return None

    return parsed


async def delete_cache_key(
    *,
    key: str,
) -> bool:
    redis = get_redis_client()

    deleted = await redis.delete(
        key,
    )

    return deleted > 0


async def set_incident_cache(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    value: dict[str, object],
    ttl_seconds: int | None = None,
) -> None:
    key = build_incident_cache_key(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    await set_cache_json(
        key=key,
        value=value,
        ttl_seconds=ttl_seconds,
    )


async def get_incident_cache(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> dict[str, object] | None:
    key = build_incident_cache_key(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    return await get_cache_json(
        key=key,
    )


async def delete_incident_cache(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> bool:
    key = build_incident_cache_key(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    return await delete_cache_key(
        key=key,
    )
