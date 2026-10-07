from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.api.routes.health as health_module
from ops_pilot.main import app

client = TestClient(app)


def test_health_check_returns_ok() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok",
    }


def test_readiness_check_returns_ready(
    monkeypatch,
) -> None:
    session_mock = AsyncMock(
        spec=AsyncSession,
    )

    session = cast(
        AsyncSession,
        session_mock,
    )

    @asynccontextmanager
    async def fake_session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    redis = AsyncMock()

    redis.ping.return_value = True

    monkeypatch.setattr(
        health_module,
        "async_session_factory",
        fake_session_factory,
    )

    monkeypatch.setattr(
        health_module,
        "get_redis_client",
        lambda: redis,
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200

    assert response.json() == {
        "status": "ready",
        "database": "connected",
        "redis": "connected",
    }

    cast(
        AsyncMock,
        session_mock.execute,
    ).assert_awaited_once()

    redis.ping.assert_awaited_once()


def test_readiness_check_returns_503_when_database_unavailable(
    monkeypatch,
) -> None:
    session_mock = AsyncMock(
        spec=AsyncSession,
    )

    session = cast(
        AsyncSession,
        session_mock,
    )

    cast(
        AsyncMock,
        session_mock.execute,
    ).side_effect = RuntimeError("database unavailable")

    @asynccontextmanager
    async def fake_session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    redis = AsyncMock()

    monkeypatch.setattr(
        health_module,
        "async_session_factory",
        fake_session_factory,
    )

    monkeypatch.setattr(
        health_module,
        "get_redis_client",
        lambda: redis,
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503

    assert response.json() == {
        "detail": "Database unavailable",
    }

    redis.ping.assert_not_awaited()


def test_readiness_check_returns_503_when_redis_unavailable(
    monkeypatch,
) -> None:
    session_mock = AsyncMock(
        spec=AsyncSession,
    )

    session = cast(
        AsyncSession,
        session_mock,
    )

    @asynccontextmanager
    async def fake_session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    redis = AsyncMock()

    redis.ping.side_effect = RuntimeError("redis unavailable")

    monkeypatch.setattr(
        health_module,
        "async_session_factory",
        fake_session_factory,
    )

    monkeypatch.setattr(
        health_module,
        "get_redis_client",
        lambda: redis,
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503

    assert response.json() == {
        "detail": "Redis unavailable",
    }

    cast(
        AsyncMock,
        session_mock.execute,
    ).assert_awaited_once()

    redis.ping.assert_awaited_once()
