from datetime import UTC, datetime

from ops_pilot.cache.redis import get_redis_client
from ops_pilot.core.config import get_settings


def _revoked_access_token_key(
    jti: str,
) -> str:
    settings = get_settings()

    return f"{settings.redis_key_prefix}:mcp:revoked-access-token:{jti}"


async def revoke_mcp_access_token(
    *,
    jti: str,
    expires_at: int,
) -> None:
    now = int(datetime.now(UTC).timestamp())

    ttl_seconds = expires_at - now

    if ttl_seconds <= 0:
        return

    redis = get_redis_client()

    await redis.set(
        _revoked_access_token_key(jti),
        "1",
        ex=ttl_seconds,
    )


async def is_mcp_access_token_revoked(
    *,
    jti: str,
) -> bool:
    redis = get_redis_client()

    value = await redis.get(_revoked_access_token_key(jti))

    return value is not None
