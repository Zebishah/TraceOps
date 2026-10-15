import uuid
from unittest.mock import AsyncMock

import pytest

from ops_pilot.services import oauth


@pytest.mark.anyio
async def test_create_authorization_code_stores_redirect_uri_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    monkeypatch.setattr(
        oauth,
        "generate_oauth_secret",
        lambda: "raw-code",
    )

    await oauth.create_authorization_code(
        session=session,
        client_id="client-123",
        user_id=uuid.uuid4(),
        redirect_uri="https://client.example/callback",
        redirect_uri_provided_explicitly=False,
        scopes=["ops-pilot:read"],
        code_challenge="challenge",
        resource="https://ops-pilot.example/mcp",
    )

    added = session.add.call_args.args[0]

    assert added.redirect_uri_provided_explicitly is False

    session.commit.assert_awaited_once()
