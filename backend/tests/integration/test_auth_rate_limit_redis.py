"""Integration tests for Redis-backed authentication rate limiting.

Each test uses a fresh Redis connection pool to prevent
cross-event-loop connection reuse under pytest-anyio.

Temporary keys are always cleaned up.
"""

import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from ops_pilot.core.config import get_settings
from ops_pilot.services import auth_rate_limit
from ops_pilot.services.auth_rate_limit import AuthRateLimitExceeded


@pytest.fixture
async def redis_client(
    monkeypatch: pytest.MonkeyPatch,
):
    """Provide an isolated Redis client for each test's event loop."""

    settings = get_settings()

    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    # The rate limiter and the test must use exactly the same
    # Redis client within the current event loop.
    monkeypatch.setattr(
        auth_rate_limit,
        "get_redis_client",
        lambda: client,
    )

    try:
        await client.ping()
        yield client
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_redis_rate_limit_blocks_concurrent_attempts(
    redis_client: Redis,
) -> None:
    """Concurrent requests share the same atomic Redis counter."""

    category = f"integration-{uuid.uuid4().hex}"
    identifier = f"account-{uuid.uuid4().hex}"

    settings = get_settings()

    key = (
        f"{settings.redis_key_prefix}:auth-rate:"
        f"{category}:{auth_rate_limit._private_key(identifier)}"
    )

    async def attempt() -> bool:
        try:
            await auth_rate_limit._enforce_limit(
                category=category,
                identifier=identifier,
                attempts=5,
                window_seconds=60,
            )
            return True
        except AuthRateLimitExceeded:
            return False

    try:
        results = await asyncio.gather(*(attempt() for _ in range(12)))

        assert results.count(True) == 5
        assert results.count(False) == 7

        count = await redis_client.get(key)
        assert int(count or 0) == 12

        ttl = await redis_client.ttl(key)
        assert 0 < ttl <= 60

    finally:
        await redis_client.delete(key)


@pytest.mark.anyio
async def test_redis_rate_limit_key_expires(
    redis_client: Redis,
) -> None:
    """Expired rate-limit windows allow fresh requests."""

    category = f"expiry-{uuid.uuid4().hex}"
    identifier = f"account-{uuid.uuid4().hex}"

    settings = get_settings()

    key = (
        f"{settings.redis_key_prefix}:auth-rate:"
        f"{category}:{auth_rate_limit._private_key(identifier)}"
    )

    try:
        # First request is allowed.
        await auth_rate_limit._enforce_limit(
            category=category,
            identifier=identifier,
            attempts=1,
            window_seconds=2,
        )

        # Second request exceeds the active limit.
        with pytest.raises(AuthRateLimitExceeded):
            await auth_rate_limit._enforce_limit(
                category=category,
                identifier=identifier,
                attempts=1,
                window_seconds=2,
            )

        # Allow the Redis key to expire.
        await asyncio.sleep(2.2)

        # A new window must allow another request.
        await auth_rate_limit._enforce_limit(
            category=category,
            identifier=identifier,
            attempts=1,
            window_seconds=2,
        )

        assert await redis_client.get(key) == "1"

    finally:
        await redis_client.delete(key)
