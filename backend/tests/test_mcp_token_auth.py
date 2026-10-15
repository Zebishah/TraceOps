import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import jwt
import pytest

from ops_pilot.core.config import get_settings
from ops_pilot.core.security import (
    create_access_token,
    create_mcp_access_token,
)
from ops_pilot.mcp.auth import (
    OpsPilotMCPTokenVerifier,
)

USER_ID = uuid.uuid4()


@pytest.mark.anyio
async def test_mcp_token_verifier_accepts_valid_mcp_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = create_mcp_access_token(
        subject=str(
            USER_ID,
        ),
    )
    monkeypatch.setattr(
        "ops_pilot.mcp.auth.is_mcp_access_token_revoked",
        AsyncMock(
            return_value=False,
        ),
    )
    verifier = OpsPilotMCPTokenVerifier()

    result = await verifier.verify_token(
        token,
    )

    assert result is not None
    assert result.subject == str(USER_ID)
    assert "ops-pilot:read" in result.scopes


@pytest.mark.anyio
async def test_mcp_token_verifier_rejects_normal_api_token() -> None:
    token = create_access_token(
        subject=str(
            USER_ID,
        ),
    )

    verifier = OpsPilotMCPTokenVerifier()

    result = await verifier.verify_token(
        token,
    )

    assert result is None


@pytest.mark.anyio
async def test_mcp_token_verifier_rejects_invalid_token() -> None:
    verifier = OpsPilotMCPTokenVerifier()

    result = await verifier.verify_token(
        "definitely-not-a-valid-token",
    )

    assert result is None


@pytest.mark.anyio
async def test_mcp_token_verifier_rejects_wrong_audience() -> None:
    settings = get_settings()

    token = jwt.encode(
        {
            "sub": str(USER_ID),
            "exp": datetime.now(UTC)
            + timedelta(
                minutes=30,
            ),
            "iss": str(settings.mcp_authorization_server_url),
            "aud": "https://attacker.example.com/mcp",
            "scope": settings.mcp_required_scope,
            "jti": str(uuid.uuid4()),
            "client_id": "test-client",
            "token_use": "mcp",
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    verifier = OpsPilotMCPTokenVerifier()

    result = await verifier.verify_token(
        token,
    )

    assert result is None


@pytest.mark.anyio
async def test_mcp_token_verifier_rejects_expired_token() -> None:
    settings = get_settings()

    token = jwt.encode(
        {
            "sub": str(USER_ID),
            "exp": datetime.now(UTC)
            - timedelta(
                minutes=1,
            ),
            "iss": str(settings.mcp_authorization_server_url),
            "aud": str(settings.mcp_resource_url),
            "scope": settings.mcp_required_scope,
            "client_id": "test-client",
            "token_use": "mcp",
            "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    verifier = OpsPilotMCPTokenVerifier()

    result = await verifier.verify_token(
        token,
    )

    assert result is None


@pytest.mark.anyio
async def test_mcp_token_verifier_rejects_revoked_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = create_mcp_access_token(
        subject=str(USER_ID),
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.auth.is_mcp_access_token_revoked",
        AsyncMock(
            return_value=True,
        ),
    )

    verifier = OpsPilotMCPTokenVerifier()

    result = await verifier.verify_token(
        token,
    )

    assert result is None
