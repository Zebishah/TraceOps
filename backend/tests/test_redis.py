from types import SimpleNamespace

import ops_pilot.cache.redis as redis_module


def test_get_redis_client_uses_configured_url(
    monkeypatch,
) -> None:
    redis_module.get_redis_client.cache_clear()

    monkeypatch.setattr(
        redis_module,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://localhost:6379/0",
        ),
    )

    client = redis_module.get_redis_client()

    assert client.connection_pool.connection_kwargs["host"] == "localhost"

    assert client.connection_pool.connection_kwargs["port"] == 6379

    assert client.connection_pool.connection_kwargs["db"] == 0

    redis_module.get_redis_client.cache_clear()
