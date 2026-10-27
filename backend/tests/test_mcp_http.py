"""HTTP transport authentication and authorization regression tests."""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from ops_pilot.core.security import (
    create_access_token,
    create_mcp_access_token,
)
from ops_pilot.main import app
from ops_pilot.mcp import server as mcp_server


def _headers(
    token: str | None = None,
    session_id: str | None = None,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }

    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id

    return headers


def _initialize_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "opspilot-http-security-test",
                "version": "1.0.0",
            },
        },
    }


def test_mcp_http_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise security scenarios under one MCP session-manager lifetime."""

    close_redis = AsyncMock()
    close_mistral = AsyncMock()
    close_voyage = AsyncMock()
    close_qdrant = AsyncMock()

    revocation_check = AsyncMock(return_value=False)

    monkeypatch.setattr(
        "ops_pilot.mcp.auth.is_mcp_access_token_revoked",
        revocation_check,
    )
    monkeypatch.setattr(
        "ops_pilot.main.close_redis_client",
        close_redis,
    )
    monkeypatch.setattr(
        "ops_pilot.main.close_mistral_embedding_client",
        close_mistral,
    )
    monkeypatch.setattr(
        "ops_pilot.main.close_voyage_reranker_client",
        close_voyage,
    )
    monkeypatch.setattr(
        "ops_pilot.main.close_qdrant_client",
        close_qdrant,
    )

    fake_authentication = AsyncMock()
    fake_investigation = AsyncMock()
    fake_knowledge_search = AsyncMock()

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
    monkeypatch.setattr(
        mcp_server,
        "search_project_knowledge_service",
        fake_knowledge_search,
    )

    user_id = uuid.uuid4()

    read_token = create_mcp_access_token(
        subject=str(user_id),
        scopes=["ops-pilot:read"],
    )

    write_token = create_mcp_access_token(
        subject=str(user_id),
        scopes=["ops-pilot:read", "ops-pilot:write"],
    )

    api_token = create_access_token(
        subject=str(user_id),
    )

    # Start the MCP session manager exactly once.
    with TestClient(
        app,
        base_url="http://localhost",
    ) as client:
        # 1. Anonymous initialization is forbidden.
        anonymous = client.post(
            "/mcp",
            headers=_headers(),
            json=_initialize_request(),
        )
        assert anonymous.status_code in {401, 403}

        # 2. REST authentication remains separate.
        rest_response = client.get("/api/v1/auth/me")
        assert rest_response.status_code in {401, 403}

        # 3. A valid MCP read token can initialize.
        initialized = client.post(
            "/mcp",
            headers=_headers(read_token),
            json=_initialize_request(),
        )
        assert initialized.status_code == 200

        session_id = initialized.headers.get("mcp-session-id")

        notification = client.post(
            "/mcp",
            headers=_headers(read_token, session_id),
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        assert notification.status_code in {200, 202, 204}

        # 4. A normal REST JWT cannot authenticate to MCP.
        normal_token_response = client.post(
            "/mcp",
            headers=_headers(api_token),
            json=_initialize_request(),
        )
        assert normal_token_response.status_code in {401, 403}

        # 5. Read-only MCP token cannot initiate investigation.
        read_only_call = client.post(
            "/mcp",
            headers=_headers(read_token, session_id),
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "investigate_incident",
                    "arguments": {
                        "incident_id": str(uuid.uuid4()),
                    },
                },
            },
        )

        assert read_only_call.status_code == 200
        assert '"isError":true' in read_only_call.text.replace(
            " ", ""
        ) or '"error":' in read_only_call.text.replace(" ", "")
        fake_authentication.assert_not_awaited()
        fake_investigation.assert_not_awaited()

        # 6. Anonymous knowledge search cannot reach Qdrant.
        anonymous_search = client.post(
            "/mcp",
            headers=_headers(),
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "search_project_knowledge",
                    "arguments": {
                        "query": "internal operational data",
                        "limit": 3,
                    },
                },
            },
        )

        assert anonymous_search.status_code in {401, 403}
        fake_knowledge_search.assert_not_awaited()

        # 7. Revoked MCP JWT cannot initialize a new session.
        revocation_check.return_value = True

        revoked_response = client.post(
            "/mcp",
            headers=_headers(write_token),
            json=_initialize_request(),
        )

        assert revoked_response.status_code in {401, 403}

        revocation_check.assert_awaited()

    # Application cleanup should run once.
    close_redis.assert_awaited_once()
    close_mistral.assert_awaited_once()
    close_voyage.assert_awaited_once()
    close_qdrant.assert_awaited_once()
