"""Authentication rate limiting security regression tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from ops_pilot.api.routes import auth as auth_routes
from ops_pilot.services import auth_rate_limit
from ops_pilot.services.auth_rate_limit import (
    AuthRateLimitExceeded,
    AuthRateLimitUnavailable,
)


@pytest.mark.anyio
async def test_rate_limiter_allows_attempt_within_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = SimpleNamespace(
        eval=AsyncMock(return_value=[3, 42]),
    )

    monkeypatch.setattr(
        auth_rate_limit,
        "get_redis_client",
        lambda: fake_redis,
    )

    await auth_rate_limit._enforce_limit(
        category="test-login",
        identifier="user@example.com",
        attempts=5,
        window_seconds=60,
    )

    fake_redis.eval.assert_awaited_once()
    args = fake_redis.eval.await_args.args

    assert args[1] == 1
    assert "test-login:" in args[2]
    assert "user@example.com" not in args[2]
    assert args[3] == 60


@pytest.mark.anyio
async def test_rate_limiter_blocks_excess_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = SimpleNamespace(
        eval=AsyncMock(return_value=[6, 37]),
    )

    monkeypatch.setattr(
        auth_rate_limit,
        "get_redis_client",
        lambda: fake_redis,
    )

    with pytest.raises(AuthRateLimitExceeded) as exc:
        await auth_rate_limit._enforce_limit(
            category="test-account",
            identifier="user@example.com",
            attempts=5,
            window_seconds=60,
        )

    assert exc.value.retry_after_seconds == 37


@pytest.mark.anyio
async def test_redis_failure_blocks_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = SimpleNamespace(
        eval=AsyncMock(side_effect=ConnectionError("Redis down")),
    )

    monkeypatch.setattr(
        auth_rate_limit,
        "get_redis_client",
        lambda: fake_redis,
    )

    with pytest.raises(AuthRateLimitUnavailable):
        await auth_rate_limit._enforce_limit(
            category="test-login",
            identifier="user@example.com",
            attempts=5,
            window_seconds=60,
        )


@pytest.mark.anyio
async def test_login_checks_ip_and_normalized_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    async def record_limit(
        *,
        category: str,
        identifier: str,
        attempts: int,
        window_seconds: int,
    ) -> None:
        seen.append((category, identifier, attempts, window_seconds))

    monkeypatch.setattr(
        auth_rate_limit,
        "_enforce_limit",
        record_limit,
    )

    fake_request = SimpleNamespace(
        client=SimpleNamespace(host="192.0.2.10"),
    )

    await auth_rate_limit.enforce_login_rate_limit(
        request=fake_request,  # type: ignore[arg-type]
        email="  USER@Example.com  ",
    )

    assert seen == [
        ("login-ip", "192.0.2.10", 10, 60),
        ("login-account", "user@example.com", 5, 300),
    ]


@pytest.mark.anyio
async def test_registration_has_its_own_ip_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    async def record_limit(
        *,
        category: str,
        identifier: str,
        attempts: int,
        window_seconds: int,
    ) -> None:
        seen.append((category, identifier, attempts, window_seconds))

    monkeypatch.setattr(
        auth_rate_limit,
        "_enforce_limit",
        record_limit,
    )

    fake_request = SimpleNamespace(
        client=SimpleNamespace(host="192.0.2.11"),
    )

    await auth_rate_limit.enforce_registration_rate_limit(
        request=fake_request,  # type: ignore[arg-type]
    )

    assert seen == [
        ("register-ip", "192.0.2.11", 5, 3600),
    ]


def test_rate_limit_error_returns_429_with_retry_after() -> None:
    with pytest.raises(HTTPException) as exc:
        auth_routes._raise_rate_limit_error(AuthRateLimitExceeded(retry_after_seconds=45))

    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "45"}


def test_unavailable_limiter_returns_503() -> None:
    with pytest.raises(HTTPException) as exc:
        auth_routes._raise_rate_limit_error(AuthRateLimitUnavailable("Redis unavailable"))

    assert exc.value.status_code == 503
