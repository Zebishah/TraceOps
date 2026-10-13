from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from ops_pilot.core.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(
    *,
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()

    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )

    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()

    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def create_mcp_access_token(
    *,
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()

    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta is not None
        else timedelta(
            minutes=settings.mcp_access_token_expire_minutes,
        )
    )

    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iss": settings.mcp_issuer_url,
        "aud": settings.mcp_resource_url,
        "scope": settings.mcp_required_scope,
        "token_use": "mcp",
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_mcp_access_token(
    token: str,
) -> dict[str, Any]:
    settings = get_settings()

    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[
            settings.jwt_algorithm,
        ],
        audience=settings.mcp_resource_url,
        issuer=settings.mcp_issuer_url,
    )

    if payload.get("token_use") != "mcp":
        raise jwt.InvalidTokenError("Token is not an MCP access token")

    return payload
