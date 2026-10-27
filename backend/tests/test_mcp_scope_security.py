import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import Client

from ops_pilot.core.mcp_scopes import (
    READ_SCOPE,
    WRITE_SCOPE,
    parse_mcp_scopes,
    validate_mcp_scope_grant,
)
from ops_pilot.core.security import create_mcp_access_token
from ops_pilot.mcp.server import mcp


@pytest.mark.parametrize(
    ("requested", "registered"),
    [
        (READ_SCOPE, READ_SCOPE),
        (READ_SCOPE, f"{READ_SCOPE} {WRITE_SCOPE}"),
        (
            f"{READ_SCOPE} {WRITE_SCOPE}",
            f"{READ_SCOPE} {WRITE_SCOPE}",
        ),
    ],
)
def test_valid_scope_grants(
    requested: str,
    registered: str,
) -> None:
    assert (
        validate_mcp_scope_grant(
            requested=requested,
            registered=registered,
        )
        == requested.split()
    )


@pytest.mark.parametrize(
    ("requested", "registered"),
    [
        (WRITE_SCOPE, WRITE_SCOPE),
        (f"{READ_SCOPE} {WRITE_SCOPE}", READ_SCOPE),
        (f"{READ_SCOPE} ops-pilot:admin", READ_SCOPE),
        (f"{READ_SCOPE} {READ_SCOPE}", READ_SCOPE),
        ("", READ_SCOPE),
    ],
)
def test_invalid_scope_grants(
    requested: str,
    registered: str,
) -> None:
    with pytest.raises(ValueError):
        validate_mcp_scope_grant(
            requested=requested,
            registered=registered,
        )


def test_parse_scopes_preserves_valid_values() -> None:
    assert parse_mcp_scopes(f"{READ_SCOPE} {WRITE_SCOPE}") == [READ_SCOPE, WRITE_SCOPE]


@pytest.mark.anyio
async def test_read_only_token_cannot_investigate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid read-only JWT cannot start an incident investigation."""

    from ops_pilot.mcp import server as mcp_server

    read_only_token = create_mcp_access_token(
        subject=str(uuid.uuid4()),
        scopes=[READ_SCOPE],
    )

    fake_investigation = AsyncMock()
    fake_authentication = AsyncMock()

    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: SimpleNamespace(
            token=read_only_token,
            scopes=[READ_SCOPE],
        ),
    )

    monkeypatch.setattr(
        mcp_server,
        "authenticate_mcp_access",
        fake_authentication,
    )

    monkeypatch.setattr(
        mcp_server,
        "investigate_incident_service",
        fake_investigation,
    )

    # The guard itself must reject the signed read-only JWT.
    with pytest.raises(
        mcp_server.MCPAuthenticationError,
        match="ops-pilot:write",
    ):
        mcp_server.require_mcp_write_scope(read_only_token)

    # The registered MCP tool must enforce that same guard
    # before invoking any database authentication.
    async with Client(mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "investigate_incident",
            {
                "incident_id": str(uuid.uuid4()),
            },
        )

    assert result.is_error is True
    assert result.structured_content is None

    fake_authentication.assert_not_awaited()
    fake_investigation.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_token_cannot_investigate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_investigation = AsyncMock()

    monkeypatch.setattr(
        "ops_pilot.mcp.server.get_access_token",
        lambda: None,
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.investigate_incident_service",
        fake_investigation,
    )

    async with Client(mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "investigate_incident",
            {
                "incident_id": str(uuid.uuid4()),
            },
        )

    assert result.is_error is True
    fake_investigation.assert_not_awaited()
