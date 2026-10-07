from types import SimpleNamespace

import pytest

import ops_pilot.cache.ttl as redis_ttl_module


def test_get_default_cache_ttl_seconds(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        redis_ttl_module,
        "get_settings",
        lambda: SimpleNamespace(
            redis_default_ttl_seconds=300,
        ),
    )

    result = redis_ttl_module.get_default_cache_ttl_seconds()

    assert result == 300


def test_default_cache_ttl_must_be_positive(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        redis_ttl_module,
        "get_settings",
        lambda: SimpleNamespace(
            redis_default_ttl_seconds=0,
        ),
    )

    with pytest.raises(
        ValueError,
        match=("Redis cache TTL must be greater than zero"),
    ):
        (redis_ttl_module.get_default_cache_ttl_seconds())
