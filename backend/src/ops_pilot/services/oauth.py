import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.config import get_settings
from ops_pilot.core.oauth_security import (
    generate_oauth_secret,
    hash_oauth_secret,
)
from ops_pilot.models.oauth_authorization_code import (
    OAuthAuthorizationCode,
)
from ops_pilot.models.oauth_client import OAuthClient
from ops_pilot.models.oauth_refresh_token import (
    OAuthRefreshToken,
)


async def get_oauth_client(
    *,
    session: AsyncSession,
    client_id: str,
) -> OAuthClient | None:
    result = await session.execute(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.is_active.is_(True),
        )
    )

    return result.scalar_one_or_none()


async def register_public_oauth_client(
    *,
    session: AsyncSession,
    client_name: str | None,
    redirect_uris: list[str],
    grant_types: list[str],
    response_types: list[str],
    scope: str,
) -> OAuthClient:
    client = OAuthClient(
        client_id=f"opspilot_{uuid.uuid4().hex}",
        client_secret_hash=None,
        client_name=client_name,
        redirect_uris_json=json.dumps(
            redirect_uris,
        ),
        grant_types_json=json.dumps(
            grant_types,
        ),
        response_types_json=json.dumps(
            response_types,
        ),
        token_endpoint_auth_method="none",
        scope=scope,
    )

    session.add(
        client,
    )

    await session.commit()
    await session.refresh(
        client,
    )

    return client


def oauth_client_redirect_uris(
    client: OAuthClient,
) -> list[str]:
    value = json.loads(client.redirect_uris_json)

    if not isinstance(
        value,
        list,
    ):
        return []

    return [
        str(item)
        for item in value
        if isinstance(
            item,
            str,
        )
    ]


async def create_authorization_code(
    *,
    session: AsyncSession,
    client_id: str,
    user_id: uuid.UUID,
    redirect_uri: str,
    scopes: list[str],
    code_challenge: str,
    resource: str,
) -> str:
    settings = get_settings()

    raw_code = generate_oauth_secret()

    code = OAuthAuthorizationCode(
        code_hash=hash_oauth_secret(raw_code),
        client_id=client_id,
        user_id=user_id,
        redirect_uri=redirect_uri,
        scopes=" ".join(scopes),
        code_challenge=code_challenge,
        resource=resource,
        expires_at=(
            datetime.now(UTC) + timedelta(minutes=(settings.mcp_authorization_code_expire_minutes))
        ),
    )

    session.add(
        code,
    )

    await session.commit()

    return raw_code


async def load_authorization_code(
    *,
    session: AsyncSession,
    raw_code: str,
    client_id: str,
) -> OAuthAuthorizationCode | None:
    result = await session.execute(
        select(OAuthAuthorizationCode).where(
            OAuthAuthorizationCode.code_hash == hash_oauth_secret(raw_code),
            OAuthAuthorizationCode.client_id == client_id,
        )
    )

    code = result.scalar_one_or_none()

    if code is None:
        return None

    if code.consumed_at is not None:
        return None

    if code.expires_at <= datetime.now(UTC):
        return None

    return code


async def consume_authorization_code(
    *,
    session: AsyncSession,
    code: OAuthAuthorizationCode,
) -> None:
    code.consumed_at = datetime.now(UTC)

    await session.commit()


async def create_refresh_token(
    *,
    session: AsyncSession,
    client_id: str,
    user_id: uuid.UUID,
    scopes: list[str],
    resource: str,
) -> str:
    settings = get_settings()

    raw_token = generate_oauth_secret()

    refresh_token = OAuthRefreshToken(
        token_hash=hash_oauth_secret(raw_token),
        client_id=client_id,
        user_id=user_id,
        scopes=" ".join(scopes),
        resource=resource,
        expires_at=(datetime.now(UTC) + timedelta(days=(settings.mcp_refresh_token_expire_days))),
    )

    session.add(
        refresh_token,
    )

    await session.commit()

    return raw_token


async def load_refresh_token(
    *,
    session: AsyncSession,
    raw_token: str,
    client_id: str,
) -> OAuthRefreshToken | None:
    result = await session.execute(
        select(OAuthRefreshToken).where(
            OAuthRefreshToken.token_hash == hash_oauth_secret(raw_token),
            OAuthRefreshToken.client_id == client_id,
        )
    )

    token = result.scalar_one_or_none()

    if token is None:
        return None

    if token.revoked_at is not None:
        return None

    if token.expires_at <= datetime.now(UTC):
        return None

    return token


async def revoke_refresh_token(
    *,
    session: AsyncSession,
    token: OAuthRefreshToken,
) -> None:
    token.revoked_at = datetime.now(UTC)

    await session.commit()
