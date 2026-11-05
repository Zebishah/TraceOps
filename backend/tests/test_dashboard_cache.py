"""Cache isolation, expiry, races, permissions and failure fallback."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from ops_pilot.cache import dashboard as cache
from tests import test_dashboard_api as dashboard_api

dashboard_client = dashboard_api.dashboard_client


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expires = {}
        self.now = 0
        self.gets = 0

    async def get(self, key):
        self.gets += 1
        if self.expires.get(key, float("inf")) <= self.now:
            self.values.pop(key, None)
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.expires[key] = self.now + ex if ex else float("inf")

    async def delete(self, key):
        self.values.pop(key, None)

    async def eval(self, _script, _count, global_key, org_key, global_value, org_value, ttl):
        result = []
        for key, value in [(global_key, global_value), (org_key, org_value)]:
            existing = await self.get(key)
            if existing is None:
                await self.set(key, value, ex=ttl)
                existing = value
            result.append(existing)
        return result

    def pipeline(self, **_kwargs):
        redis = self

        class Pipeline:
            def __init__(self):
                self.commands = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

            def set(self, *args, **kwargs):
                self.commands.append((args, kwargs))

            async def execute(self):
                for args, kwargs in self.commands:
                    await redis.set(*args, **kwargs)

        return Pipeline()


@pytest.fixture
def redis(monkeypatch):
    value = FakeRedis()
    monkeypatch.setattr(cache, "get_redis_client", lambda: value)
    return value


def arguments(org=None, user=None, role="owner", refresh=False):
    return {
        "organization_id": org or uuid.uuid4(),
        "membership": SimpleNamespace(user_id=user or uuid.uuid4(), role=role),
        "request": Request(
            {"type": "http", "headers": [(b"x-opspilot-refresh", b"1")] if refresh else []}
        ),
        "session": None,
    }


@pytest.mark.anyio
async def test_hits_are_isolated_by_tenant_user_role_and_filter_and_expire(redis):
    calls = 0

    @cache.dashboard_cached
    async def read(**kwargs) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": calls}

    first = arguments()
    assert await read(**first, q="one") == {"value": 1}
    assert await read(**first, q="one") == {"value": 1}
    assert await read(**first, q="two") == {"value": 2}
    assert await read(**arguments(), q="one") == {"value": 3}
    assert await read(
        **(
            first
            | {"membership": SimpleNamespace(user_id=first["membership"].user_id, role="viewer")}
        ),
        q="one",
    ) == {"value": 4}
    redis.now += cache.CACHE_TTL_SECONDS + 1
    assert await read(**first, q="one") == {"value": 5}


@pytest.mark.anyio
async def test_tenant_rotation_and_manual_refresh_bypass_old_data(redis):
    current = 1

    @cache.dashboard_cached
    async def read(**kwargs) -> dict[str, int]:
        return {"value": current}

    args = arguments()
    assert await read(**args) == {"value": 1}
    current = 2
    # Browsers/proxies can add no-cache for their HTTP cache; it must not disable Redis.
    args["request"] = Request({"type": "http", "headers": [(b"cache-control", b"no-cache")]})
    assert await read(**args) == {"value": 1}
    await cache.invalidate_dashboard_cache({str(args["organization_id"])})
    assert await read(**args) == {"value": 2}
    current = 3
    fresh = args | {"request": arguments(refresh=True)["request"]}
    assert await read(**fresh) == {"value": 3}


@pytest.mark.anyio
async def test_late_reader_cannot_refill_the_active_namespace(redis):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    @cache.dashboard_cached
    async def read(**kwargs) -> dict[str, int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
            return {"value": 1}
        return {"value": 2}

    args = arguments()
    old = asyncio.create_task(read(**args))
    await entered.wait()
    await cache.invalidate_dashboard_cache({str(args["organization_id"])})
    assert await read(**args) == {"value": 2}
    release.set()
    assert await old == {"value": 1}
    assert await read(**args) == {"value": 2}
    assert calls == 2


@pytest.mark.anyio
async def test_missing_version_keys_never_revive_old_responses(redis):
    calls = 0

    @cache.dashboard_cached
    async def read(**kwargs) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": calls}

    args = arguments()
    await read(**args)
    await redis.delete(cache.version_key(str(args["organization_id"])))
    assert await read(**args) == {"value": 2}


@pytest.mark.anyio
async def test_cache_corruption_or_redis_outage_never_breaks_database_reads(redis, monkeypatch):
    @cache.dashboard_cached
    async def read(**kwargs) -> dict[str, int]:
        return {"value": 1}

    args = arguments()
    await read(**args)
    key = next(key for key in redis.values if ":version:" not in key)
    redis.values[key] = '{"value":"not-an-integer"}'
    assert await read(**args) == {"value": 1}

    def unavailable():
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(cache, "get_redis_client", unavailable)
    assert await read(**args) == {"value": 1}
    await cache.invalidate_dashboard_cache({"*"})


@pytest.mark.anyio
async def test_failed_reads_are_not_cached(redis):
    @cache.dashboard_cached
    async def read(**kwargs) -> dict[str, int]:
        raise ValueError("Database unavailable")

    with pytest.raises(ValueError):
        await read(**arguments())
    assert not any(":version:" not in key for key in redis.values)


@pytest.mark.asyncio
async def test_authorization_runs_before_cache_hits_and_pages_preserve_filters(
    redis, dashboard_client
):
    client, orgs, *_ = dashboard_client
    url = f"/api/v1/organizations/{orgs[0]}/dashboard/resources/incidents"
    first = await client.get(url)
    second = await client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert (await client.get(url, params={"q": "Ordinary"})).json()["total"] == 1
    before = redis.gets
    denied = await client.get(url.replace(str(orgs[0]), str(orgs[1])))
    assert denied.status_code == 403
    assert redis.gets == before
