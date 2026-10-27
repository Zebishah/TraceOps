"""OAuth one-time grant and scope security regressions."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.mcp import oauth_provider
from ops_pilot.services import oauth

USER_ID = uuid.uuid4()
CLIENT_ID = "test-client"
RESOURCE = "https://example.test/mcp"


def make_session_context(session):
    context = Mock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


@pytest.mark.anyio
async def test_code_claim_uses_conditional_update() -> None:
    session = AsyncMock()
    result = Mock()
    result.scalar_one_or_none.return_value = uuid.uuid4()
    session.execute.return_value = result

    code = SimpleNamespace(
        id=uuid.uuid4(),
        client_id=CLIENT_ID,
        code_hash="stored-hash",
    )

    assert await oauth.consume_authorization_code(
        session=session,
        code=code,
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()

    sql = str(compiled).lower()

    assert "update oauth_authorization_codes" in sql
    assert "consumed_at is null" in sql
    assert "expires_at >" in sql
    assert "returning" in sql

    session.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_refresh_revocation_uses_conditional_update() -> None:
    session = AsyncMock()
    result = Mock()
    result.scalar_one_or_none.return_value = uuid.uuid4()
    session.execute.return_value = result

    token = SimpleNamespace(
        id=uuid.uuid4(),
        client_id=CLIENT_ID,
        token_hash="stored-refresh-hash",
    )

    assert await oauth.revoke_refresh_token(
        session=session,
        token=token,
        commit=False,
    )

    sql = str(session.execute.await_args.args[0].compile()).lower()

    assert "update oauth_refresh_tokens" in sql
    assert "revoked_at is null" in sql
    assert "expires_at >" in sql
    assert "returning" in sql

    session.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_code_claim_rejects_lost_race() -> None:
    session = AsyncMock()
    result = Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    code = SimpleNamespace(
        id=uuid.uuid4(),
        client_id=CLIENT_ID,
        code_hash="hash",
    )

    claimed = await oauth.consume_authorization_code(
        session=session,
        code=code,
    )

    assert claimed is False


@pytest.mark.anyio
async def test_refresh_rotation_rejects_scope_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    stored = SimpleNamespace(
        id=uuid.uuid4(),
        client_id=CLIENT_ID,
        token_hash="hash",
        user_id=USER_ID,
        scopes="ops-pilot:read",
        resource=RESOURCE,
        revoked_at=None,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    load = AsyncMock(return_value=stored)
    revoke = AsyncMock()

    monkeypatch.setattr(
        oauth_provider,
        "async_session_factory",
        lambda: make_session_context(session),
    )
    monkeypatch.setattr(
        oauth_provider,
        "load_refresh_token",
        load,
    )
    monkeypatch.setattr(
        oauth_provider,
        "revoke_refresh_token",
        revoke,
    )

    provider = oauth_provider.OpsPilotOAuthProvider()

    from mcp.server.auth.provider import RefreshToken, TokenError
    from mcp.shared.auth import OAuthClientInformationFull

    client = OAuthClientInformationFull(
        client_id=CLIENT_ID,
        redirect_uris=["https://example.test/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope="ops-pilot:read",
    )

    caller_token = RefreshToken(
        token="raw-refresh-token",
        client_id=CLIENT_ID,
        scopes=["ops-pilot:read", "ops-pilot:write"],
        expires_at=int(stored.expires_at.timestamp()),
        resource=RESOURCE,
        subject=str(USER_ID),
    )

    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(
            client=client,
            refresh_token=caller_token,
            scopes=["ops-pilot:write"],
        )

    revoke.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_refresh_creation_can_defer_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.add = Mock()

    monkeypatch.setattr(
        oauth,
        "generate_oauth_secret",
        lambda: "new-refresh-secret",
    )

    raw = await oauth.create_refresh_token(
        session=session,
        client_id=CLIENT_ID,
        user_id=USER_ID,
        scopes=["ops-pilot:read"],
        resource=RESOURCE,
        commit=False,
    )

    assert raw == "new-refresh-secret"
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()

    created = session.add.call_args.args[0]

    assert created.user_id == USER_ID
    assert created.scopes == "ops-pilot:read"
    assert created.resource == RESOURCE
