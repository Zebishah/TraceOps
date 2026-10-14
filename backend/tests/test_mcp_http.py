import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from ops_pilot.core.security import (
    create_access_token,
    create_mcp_access_token,
)
from ops_pilot.main import app


def test_mcp_http_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_redis = AsyncMock()
    close_mistral = AsyncMock()
    close_voyage = AsyncMock()
    close_qdrant = AsyncMock()

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

    user_id = uuid.uuid4()

    mcp_token = create_mcp_access_token(
        subject=str(user_id),
    )

    api_token = create_access_token(
        subject=str(user_id),
    )

    initialize_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "ops-pilot-test",
                "version": "1.0.0",
            },
        },
    }

    with TestClient(app) as client:
        anonymous_response = client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": ("application/json, text/event-stream"),
            },
            json=initialize_request,
        )

        assert anonymous_response.status_code in {
            401,
            403,
        }

        rest_response = client.get(
            "/api/v1/auth/me",
        )

        assert rest_response.status_code in {
            401,
            403,
        }

        valid_mcp_response = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {mcp_token}",
                "Content-Type": "application/json",
                "Accept": ("application/json, text/event-stream"),
            },
            json=initialize_request,
        )

        assert valid_mcp_response.status_code == 200

        normal_api_token_response = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "Accept": ("application/json, text/event-stream"),
            },
            json=initialize_request,
        )

        assert normal_api_token_response.status_code in {
            401,
            403,
        }

    close_redis.assert_awaited_once()
    close_mistral.assert_awaited_once()
    close_voyage.assert_awaited_once()
    close_qdrant.assert_awaited_once()
