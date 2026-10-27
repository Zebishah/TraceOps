"""MCP service authentication and revocation regression tests."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ops_pilot.services import mcp_auth
from ops_pilot.services.mcp_auth import MCPAuthenticationError


@pytest.mark.anyio
async def test_revoked_token_is_rejected_before_user_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_mcp_access_token",
        lambda token: {
            "sub": str(uuid.uuid4()),
            "jti": "revoked-token-123",
        },
    )

    async def is_revoked(*, jti: str) -> bool:
        assert jti == "revoked-token-123"
        return True

    monkeypatch.setattr(
        mcp_auth,
        "is_mcp_access_token_revoked",
        is_revoked,
    )

    with pytest.raises(
        MCPAuthenticationError,
        match="revoked",
    ):
        await mcp_auth.authenticate_mcp_access(
            session=session,
            access_token="revoked-access-token",
        )

    session.get.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_jti_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_mcp_access_token",
        lambda token: {
            "sub": str(uuid.uuid4()),
        },
    )

    with pytest.raises(
        MCPAuthenticationError,
        match="token ID",
    ):
        await mcp_auth.authenticate_mcp_access(
            session=session,
            access_token="missing-jti-token",
        )

    session.get.assert_not_awaited()


@pytest.mark.anyio
async def test_revocation_store_failure_rejects_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_mcp_access_token",
        lambda token: {
            "sub": str(uuid.uuid4()),
            "jti": "check-fails",
        },
    )

    async def unavailable(*, jti: str) -> bool:
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(
        mcp_auth,
        "is_mcp_access_token_revoked",
        unavailable,
    )

    with pytest.raises(
        MCPAuthenticationError,
        match="Unable to verify",
    ):
        await mcp_auth.authenticate_mcp_access(
            session=session,
            access_token="revocation-unknown-token",
        )

    session.get.assert_not_awaited()


@pytest.mark.anyio
async def test_valid_nonrevoked_token_authenticates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    expected_user = SimpleNamespace(
        id=user_id,
        is_active=True,
    )

    monkeypatch.setattr(
        mcp_auth,
        "decode_mcp_access_token",
        lambda token: {
            "sub": str(user_id),
            "jti": "valid-token-123",
        },
    )

    async def not_revoked(*, jti: str) -> bool:
        assert jti == "valid-token-123"
        return False

    monkeypatch.setattr(
        mcp_auth,
        "is_mcp_access_token_revoked",
        not_revoked,
    )

    session.get.return_value = expected_user

    user = await mcp_auth._get_authenticated_mcp_user(
        session=session,
        access_token="valid-access-token",
    )

    assert user is expected_user
    session.get.assert_awaited_once()
