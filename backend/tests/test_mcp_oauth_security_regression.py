import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.models.membership import MembershipRole
from ops_pilot.schemas.mcp_auth import MCPAuthenticatedContext
from ops_pilot.services import mcp_auth, oauth
from ops_pilot.services.mcp_auth import (
    MCPAuthorizationError,
    authenticate_mcp_access,
    require_mcp_investigation_role,
)

USER_ID = uuid.uuid4()
ORGANIZATION_A = uuid.uuid4()
ORGANIZATION_B = uuid.uuid4()


@pytest.fixture(autouse=True)
def mock_mcp_revocation_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def not_revoked(*, jti: str) -> bool:
        return False

    monkeypatch.setattr(
        mcp_auth,
        "is_mcp_access_token_revoked",
        not_revoked,
    )


@pytest.mark.anyio
async def test_mcp_rejects_foreign_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_mcp_access_token",
        lambda token: {
            "sub": str(USER_ID),
            "jti": "unit-test-token-id",
        },
    )

    session.get.return_value = SimpleNamespace(
        id=USER_ID,
        is_active=True,
    )

    result = Mock()
    result.scalars.return_value.all.return_value = []

    session.execute.return_value = result

    with pytest.raises(
        MCPAuthorizationError,
        match="User does not have access to this organization",
    ):
        await authenticate_mcp_access(
            session=session,
            access_token="valid-token",
            organization_id=ORGANIZATION_B,
        )

    statement = session.execute.await_args.args[0]

    compiled = statement.compile()

    values = list(compiled.params.values())

    assert USER_ID in values
    assert ORGANIZATION_B in values


@pytest.mark.anyio
async def test_mcp_returns_membership_organization_as_trusted_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_mcp_access_token",
        lambda token: {
            "sub": str(USER_ID),
            "jti": "unit-test-token-id",
        },
    )

    session.get.return_value = SimpleNamespace(
        id=USER_ID,
        is_active=True,
    )

    membership = SimpleNamespace(
        organization_id=ORGANIZATION_A,
        user_id=USER_ID,
        role=MembershipRole.OPERATOR,
    )

    result = Mock()
    result.scalars.return_value.all.return_value = [
        membership,
    ]

    session.execute.return_value = result

    context = await authenticate_mcp_access(
        session=session,
        access_token="valid-token",
        organization_id=ORGANIZATION_A,
    )

    assert context.user_id == USER_ID
    assert context.organization_id == ORGANIZATION_A
    assert context.role == MembershipRole.OPERATOR


@pytest.mark.anyio
async def test_mcp_requires_explicit_organization_when_user_has_multiple_orgs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        mcp_auth,
        "decode_mcp_access_token",
        lambda token: {
            "sub": str(USER_ID),
            "jti": "unit-test-token-id",
        },
    )

    session.get.return_value = SimpleNamespace(
        id=USER_ID,
        is_active=True,
    )

    result = Mock()

    result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            organization_id=ORGANIZATION_A,
            user_id=USER_ID,
            role=MembershipRole.OPERATOR,
        ),
        SimpleNamespace(
            organization_id=ORGANIZATION_B,
            user_id=USER_ID,
            role=MembershipRole.VIEWER,
        ),
    ]

    session.execute.return_value = result

    with pytest.raises(
        MCPAuthorizationError,
        match="Multiple organizations are available",
    ):
        await authenticate_mcp_access(
            session=session,
            access_token="valid-token",
        )


@pytest.mark.parametrize(
    "role",
    [
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.OPERATOR,
        MembershipRole.REVIEWER,
    ],
)
def test_mcp_investigation_allows_authorized_roles(
    role: MembershipRole,
) -> None:
    context = MCPAuthenticatedContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_A,
        role=role,
    )

    require_mcp_investigation_role(
        context,
    )


def test_mcp_investigation_rejects_viewer() -> None:
    context = MCPAuthenticatedContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_A,
        role=MembershipRole.VIEWER,
    )

    with pytest.raises(
        MCPAuthorizationError,
        match="cannot start incident investigations",
    ):
        require_mcp_investigation_role(
            context,
        )


@pytest.mark.anyio
async def test_consumed_authorization_code_cannot_be_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    code = SimpleNamespace(
        consumed_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    result = Mock()
    result.scalar_one_or_none.return_value = code

    session.execute.return_value = result

    monkeypatch.setattr(
        oauth,
        "hash_oauth_secret",
        lambda value: "hashed-code",
    )

    loaded = await oauth.load_authorization_code(
        session=session,
        raw_code="already-used-code",
        client_id="client-123",
    )

    assert loaded is None


@pytest.mark.anyio
async def test_expired_authorization_code_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    code = SimpleNamespace(
        consumed_at=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    result = Mock()
    result.scalar_one_or_none.return_value = code

    session.execute.return_value = result

    monkeypatch.setattr(
        oauth,
        "hash_oauth_secret",
        lambda value: "hashed-code",
    )

    loaded = await oauth.load_authorization_code(
        session=session,
        raw_code="expired-code",
        client_id="client-123",
    )

    assert loaded is None


@pytest.mark.anyio
async def test_revoked_refresh_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    token = SimpleNamespace(
        revoked_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    result = Mock()
    result.scalar_one_or_none.return_value = token

    session.execute.return_value = result

    monkeypatch.setattr(
        oauth,
        "hash_oauth_secret",
        lambda value: "hashed-refresh",
    )

    loaded = await oauth.load_refresh_token(
        session=session,
        raw_token="revoked-token",
        client_id="client-123",
    )

    assert loaded is None


@pytest.mark.anyio
async def test_expired_refresh_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    token = SimpleNamespace(
        revoked_at=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    result = Mock()
    result.scalar_one_or_none.return_value = token

    session.execute.return_value = result

    monkeypatch.setattr(
        oauth,
        "hash_oauth_secret",
        lambda value: "hashed-refresh",
    )

    loaded = await oauth.load_refresh_token(
        session=session,
        raw_token="expired-token",
        client_id="client-123",
    )

    assert loaded is None


@pytest.mark.anyio
async def test_refresh_token_lookup_is_bound_to_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    result = Mock()
    result.scalar_one_or_none.return_value = None

    session.execute.return_value = result

    monkeypatch.setattr(
        oauth,
        "hash_oauth_secret",
        lambda value: "hashed-refresh",
    )

    loaded = await oauth.load_refresh_token(
        session=session,
        raw_token="refresh-token",
        client_id="expected-client",
    )

    assert loaded is None

    statement = session.execute.await_args.args[0]

    compiled = statement.compile()

    values = list(compiled.params.values())

    assert "hashed-refresh" in values
    assert "expected-client" in values
