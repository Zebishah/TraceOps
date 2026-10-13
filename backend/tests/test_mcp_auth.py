import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import jwt
import pytest

from ops_pilot.models.membership import MembershipRole
from ops_pilot.services import mcp_auth
from ops_pilot.services.mcp_auth import (
    MCPAuthenticationError,
    MCPAuthorizationError,
    authenticate_mcp_access,
)

USER_ID = uuid.uuid4()
ORGANIZATION_ID = uuid.uuid4()


@pytest.mark.anyio
async def test_authenticate_mcp_access_returns_trusted_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_access_token",
        lambda token: {
            "sub": str(USER_ID),
        },
    )

    user = SimpleNamespace(
        id=USER_ID,
        is_active=True,
    )

    session.get.return_value = user

    membership = SimpleNamespace(
        organization_id=ORGANIZATION_ID,
        user_id=USER_ID,
        role=MembershipRole.OPERATOR,
    )

    result = Mock()
    result.scalar_one_or_none.return_value = membership

    session.execute.return_value = result

    context = await authenticate_mcp_access(
        session=session,
        access_token="valid-token",
        organization_id=ORGANIZATION_ID,
    )

    assert context.user_id == USER_ID
    assert context.organization_id == ORGANIZATION_ID
    assert context.role == MembershipRole.OPERATOR

    session.get.assert_awaited_once()
    session.execute.assert_awaited_once()


@pytest.mark.anyio
async def test_authenticate_mcp_access_rejects_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    def fake_decode_access_token(
        token: str,
    ) -> dict[str, object]:
        raise jwt.InvalidTokenError("invalid token")

    monkeypatch.setattr(
        mcp_auth,
        "decode_access_token",
        fake_decode_access_token,
    )

    with pytest.raises(
        MCPAuthenticationError,
        match="Invalid or expired access token",
    ):
        await authenticate_mcp_access(
            session=session,
            access_token="bad-token",
            organization_id=ORGANIZATION_ID,
        )

    session.get.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_authenticate_mcp_access_rejects_missing_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_access_token",
        lambda token: {},
    )

    with pytest.raises(
        MCPAuthenticationError,
        match="Access token does not contain a subject",
    ):
        await authenticate_mcp_access(
            session=session,
            access_token="token-without-subject",
            organization_id=ORGANIZATION_ID,
        )

    session.get.assert_not_awaited()


@pytest.mark.anyio
async def test_authenticate_mcp_access_rejects_inactive_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_access_token",
        lambda token: {
            "sub": str(USER_ID),
        },
    )

    session.get.return_value = SimpleNamespace(
        id=USER_ID,
        is_active=False,
    )

    with pytest.raises(
        MCPAuthenticationError,
        match="Authenticated user is not available",
    ):
        await authenticate_mcp_access(
            session=session,
            access_token="valid-token",
            organization_id=ORGANIZATION_ID,
        )

    session.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_authenticate_mcp_access_rejects_foreign_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_access_token",
        lambda token: {
            "sub": str(USER_ID),
        },
    )

    session.get.return_value = SimpleNamespace(
        id=USER_ID,
        is_active=True,
    )

    result = Mock()
    result.scalar_one_or_none.return_value = None

    session.execute.return_value = result

    with pytest.raises(
        MCPAuthorizationError,
        match="User does not have access to this organization",
    ):
        await authenticate_mcp_access(
            session=session,
            access_token="valid-token",
            organization_id=ORGANIZATION_ID,
        )

    session.execute.assert_awaited_once()
