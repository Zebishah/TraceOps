from unittest.mock import AsyncMock

import pytest

from ops_pilot.services import mcp_token_revocation


@pytest.mark.anyio
async def test_is_mcp_access_token_revoked_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = AsyncMock()

    redis.get.return_value = "1"

    monkeypatch.setattr(
        mcp_token_revocation,
        "get_redis_client",
        lambda: redis,
    )

    result = await mcp_token_revocation.is_mcp_access_token_revoked(
        jti="token-123",
    )

    assert result is True


@pytest.mark.anyio
async def test_is_mcp_access_token_revoked_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = AsyncMock()

    redis.get.return_value = None

    monkeypatch.setattr(
        mcp_token_revocation,
        "get_redis_client",
        lambda: redis,
    )

    result = await mcp_token_revocation.is_mcp_access_token_revoked(
        jti="token-123",
    )

    assert result is False


@pytest.mark.anyio
async def test_revoke_mcp_access_token_sets_redis_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = AsyncMock()

    monkeypatch.setattr(
        mcp_token_revocation,
        "get_redis_client",
        lambda: redis,
    )

    await mcp_token_revocation.revoke_mcp_access_token(
        jti="token-123",
        expires_at=4_000_000_000,
    )

    redis.set.assert_awaited_once()

    args = redis.set.await_args.args
    kwargs = redis.set.await_args.kwargs

    assert args[1] == "1"
    assert kwargs["ex"] > 0
