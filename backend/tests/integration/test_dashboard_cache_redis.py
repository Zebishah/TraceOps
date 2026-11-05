"""Exercise real Redis Lua version creation, TTLs and atomic namespace rotation."""

import uuid
from types import SimpleNamespace

import pytest
from redis.asyncio import Redis
from starlette.requests import Request

from ops_pilot.cache import dashboard as cache

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_dashboard_cache_redis_versions_expiry_and_commit_rotation(monkeypatch):
    redis = Redis.from_url(
        "redis://127.0.0.1:6379/15", decode_responses=True, socket_connect_timeout=1
    )
    prefix = f"opspilot-cache-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(cache, "get_redis_client", lambda: redis)
    monkeypatch.setattr(cache, "get_settings", lambda: SimpleNamespace(redis_key_prefix=prefix))
    calls = 0

    @cache.dashboard_cached
    async def read(**kwargs) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"count": calls}

    org = uuid.uuid4()
    arguments = {
        "organization_id": org,
        "membership": SimpleNamespace(user_id=uuid.uuid4(), role="owner"),
        "request": Request({"type": "http", "headers": []}),
    }
    try:
        await redis.ping()
        assert await read(**arguments) == {"count": 1}
        assert await read(**arguments) == {"count": 1}
        keys = [key async for key in redis.scan_iter(match=f"{prefix}:v2:dashboard:*")]
        response = next(key for key in keys if ":version:" not in key)
        assert 0 < await redis.ttl(response) <= 30
        await cache.invalidate_dashboard_cache({str(org)})
        assert await read(**arguments) == {"count": 2}
        # The older response can remain physically present; it is no longer addressable.
        assert await redis.exists(response)
        await cache.invalidate_dashboard_cache({"*"})
        assert await read(**arguments) == {"count": 3}
        await redis.delete(cache.version_key(str(org)))
        assert await read(**arguments) == {"count": 4}
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
