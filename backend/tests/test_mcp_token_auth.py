import uuid

import pytest

from ops_pilot.core.security import (
    create_access_token,
    create_mcp_access_token,
)
from ops_pilot.mcp.auth import (
    OpsPilotMCPTokenVerifier,
)

USER_ID = uuid.uuid4()


@pytest.mark.anyio
async def test_mcp_token_verifier_accepts_valid_mcp_token() -> None:
    token = create_mcp_access_token(
        subject=str(
            USER_ID,
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
