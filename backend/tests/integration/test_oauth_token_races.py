"""Prove PostgreSQL permits only one OAuth token redemption.

Uses only the explicitly designated test database.
Creates uniquely identified records and cleans them up afterward.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from dotenv import dotenv_values
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ops_pilot.core.oauth_security import hash_oauth_secret
from ops_pilot.models.oauth_authorization_code import OAuthAuthorizationCode
from ops_pilot.models.oauth_refresh_token import OAuthRefreshToken
from ops_pilot.models.user import User
from ops_pilot.services.oauth import (
    consume_authorization_code,
    revoke_refresh_token,
)


def dedicated_database_url() -> str:
    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Dedicated test database confirmation required")

    env = dotenv_values(".env")
    main_url = env.get("DATABASE_URL")
    test_url = env.get("OPSPILOT_TEST_DATABASE_URL")

    if not main_url or not test_url:
        pytest.skip("Dedicated database URLs unavailable")

    main = make_url(main_url)
    test = make_url(test_url)

    def identity(url):
        return (
            url.host,
            url.port or 5432,
            url.database,
            url.username,
        )

    if identity(main) == identity(test):
        pytest.fail("Refusing to access main database")

    if test.get_backend_name() != "postgresql":
        pytest.fail("PostgreSQL required")

    if "us-east-2.aws.neon.tech" not in (test.host or ""):
        pytest.fail("Unexpected test database endpoint")

    return test_url


@pytest.mark.anyio
async def test_authorization_code_has_one_winner() -> None:
    engine = create_async_engine(dedicated_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    user_id = uuid.uuid4()
    code_id = uuid.uuid4()
    client_id = f"race-{uuid.uuid4().hex}"
    raw_code = f"code-{uuid.uuid4().hex}"

    async def attempt() -> bool:
        async with sessions() as session:
            code = (
                await session.execute(
                    select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.id == code_id)
                )
            ).scalar_one()

            won = await consume_authorization_code(
                session=session,
                code=code,
            )

            if won:
                await session.commit()
            else:
                await session.rollback()

            return won

    try:
        async with sessions() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"race-{user_id}@example.test",
                    full_name="OAuth Race Test",
                    password_hash="not-a-real-password-hash",
                )
            )
            await session.flush()

            session.add(
                OAuthAuthorizationCode(
                    id=code_id,
                    client_id=client_id,
                    user_id=user_id,
                    code_hash=hash_oauth_secret(raw_code),
                    redirect_uri="https://example.test/callback",
                    redirect_uri_provided_explicitly=True,
                    scopes="ops-pilot:read",
                    code_challenge="test-challenge",
                    resource="https://example.test/mcp",
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
            await session.commit()

        outcomes = await asyncio.wait_for(
            asyncio.gather(attempt(), attempt()),
            timeout=20,
        )

        assert sorted(outcomes) == [False, True]

    finally:
        async with sessions() as session:
            await session.execute(
                delete(OAuthAuthorizationCode).where(OAuthAuthorizationCode.id == code_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()

        await engine.dispose()


@pytest.mark.anyio
async def test_refresh_token_has_one_rotation_winner() -> None:
    engine = create_async_engine(dedicated_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    user_id = uuid.uuid4()
    refresh_id = uuid.uuid4()
    client_id = f"refresh-race-{uuid.uuid4().hex}"
    raw_token = f"refresh-{uuid.uuid4().hex}"

    async def attempt() -> bool:
        async with sessions() as session:
            token = (
                await session.execute(
                    select(OAuthRefreshToken).where(OAuthRefreshToken.id == refresh_id)
                )
            ).scalar_one()

            won = await revoke_refresh_token(
                session=session,
                token=token,
                commit=False,
            )

            if won:
                await session.commit()
            else:
                await session.rollback()

            return won

    try:
        async with sessions() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"refresh-{user_id}@example.test",
                    full_name="OAuth Refresh Race Test",
                    password_hash="not-a-real-password-hash",
                )
            )
            await session.flush()

            session.add(
                OAuthRefreshToken(
                    id=refresh_id,
                    token_hash=hash_oauth_secret(raw_token),
                    client_id=client_id,
                    user_id=user_id,
                    scopes="ops-pilot:read",
                    resource="https://example.test/mcp",
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            await session.commit()

        outcomes = await asyncio.wait_for(
            asyncio.gather(attempt(), attempt()),
            timeout=20,
        )

        assert sorted(outcomes) == [False, True]

    finally:
        async with sessions() as session:
            await session.execute(
                delete(OAuthRefreshToken).where(OAuthRefreshToken.id == refresh_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()

        await engine.dispose()
