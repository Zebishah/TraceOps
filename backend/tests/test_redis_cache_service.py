import asyncio
import uuid
from typing import cast

import ops_pilot.cache.service as cache_service


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
    ) -> bool:
        self.values[key] = value
        self.expirations[key] = ex

        return True

    async def get(
        self,
        key: str,
    ) -> str | None:
        return self.values.get(
            key,
        )

    async def delete(
        self,
        key: str,
    ) -> int:
        existed = key in self.values

        self.values.pop(
            key,
            None,
        )

        self.expirations.pop(
            key,
            None,
        )

        return 1 if existed else 0


def test_set_and_get_cache_json(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    monkeypatch.setattr(
        cache_service,
        "get_redis_client",
        lambda: cast(
            object,
            redis,
        ),
    )

    monkeypatch.setattr(
        cache_service,
        "get_default_cache_ttl_seconds",
        lambda: 300,
    )

    async def run() -> None:
        await cache_service.set_cache_json(
            key="test:key",
            value={
                "status": "ready",
                "count": 2,
            },
        )

        result = await cache_service.get_cache_json(
            key="test:key",
        )

        assert result == {
            "status": "ready",
            "count": 2,
        }

        assert redis.expirations["test:key"] == 300

    asyncio.run(run())


def test_set_cache_uses_custom_ttl(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    monkeypatch.setattr(
        cache_service,
        "get_redis_client",
        lambda: cast(
            object,
            redis,
        ),
    )

    async def run() -> None:
        await cache_service.set_cache_json(
            key="test:key",
            value={
                "status": "ready",
            },
            ttl_seconds=60,
        )

        assert redis.expirations["test:key"] == 60

    asyncio.run(run())


def test_get_cache_returns_none_when_missing(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    monkeypatch.setattr(
        cache_service,
        "get_redis_client",
        lambda: cast(
            object,
            redis,
        ),
    )

    result = asyncio.run(
        cache_service.get_cache_json(
            key="missing:key",
        )
    )

    assert result is None


def test_invalid_cached_json_is_deleted(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    redis.values["bad:key"] = "this-is-not-json"

    monkeypatch.setattr(
        cache_service,
        "get_redis_client",
        lambda: cast(
            object,
            redis,
        ),
    )

    result = asyncio.run(
        cache_service.get_cache_json(
            key="bad:key",
        )
    )

    assert result is None

    assert "bad:key" not in redis.values


def test_delete_cache_key(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    redis.values["test:key"] = "{}"

    monkeypatch.setattr(
        cache_service,
        "get_redis_client",
        lambda: cast(
            object,
            redis,
        ),
    )

    result = asyncio.run(
        cache_service.delete_cache_key(
            key="test:key",
        )
    )

    assert result is True

    assert "test:key" not in redis.values


def test_incident_cache_uses_tenant_key(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    monkeypatch.setattr(
        cache_service,
        "get_redis_client",
        lambda: cast(
            object,
            redis,
        ),
    )

    monkeypatch.setattr(
        cache_service,
        "get_default_cache_ttl_seconds",
        lambda: 300,
    )

    async def run() -> None:
        await cache_service.set_incident_cache(
            organization_id=organization_id,
            incident_id=incident_id,
            value={
                "status": "investigating",
            },
        )

        expected_key = f"ops_pilot:v1:cache:org:{organization_id}:incident:{incident_id}"

        assert expected_key in redis.values

    asyncio.run(run())
