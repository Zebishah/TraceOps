import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from ops_pilot.api.dependencies import get_current_user
from ops_pilot.api.routes import auth as auth_routes
from ops_pilot.db.session import get_db_session
from ops_pilot.main import app
from ops_pilot.services.auth import (
    EmailAlreadyRegisteredError,
    OrganizationSlugAlreadyExistsError,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def bypass_rate_limits_for_existing_auth_api_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolate unrelated API tests from Redis.

    Dedicated rate-limiter tests verify the security behavior.
    """

    async def allow_registration(*, request: object) -> None:
        return None

    async def allow_login(
        *,
        request: object,
        email: str,
    ) -> None:
        return None

    monkeypatch.setattr(
        auth_routes,
        "enforce_registration_rate_limit",
        allow_registration,
    )

    monkeypatch.setattr(
        auth_routes,
        "enforce_login_rate_limit",
        allow_login,
    )


async def fake_db_session() -> AsyncMock:
    return AsyncMock()


def test_register_returns_conflict_for_duplicate_email(
    monkeypatch,
) -> None:
    async def fake_register_user(
        session,
        payload,
    ):
        raise EmailAlreadyRegisteredError

    monkeypatch.setattr(
        auth_routes,
        "register_user",
        fake_register_user,
    )

    app.dependency_overrides[get_db_session] = fake_db_session

    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "zohaib@example.com",
                "full_name": "Zohaib Haider",
                "password": "StrongPassword123!",
                "organization_name": "Zohaib Labs",
                "organization_slug": "zohaib-labs",
            },
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "Email already registered"}

    finally:
        app.dependency_overrides.clear()


def test_register_returns_conflict_for_duplicate_slug(
    monkeypatch,
) -> None:
    async def fake_register_user(
        session,
        payload,
    ):
        raise OrganizationSlugAlreadyExistsError

    monkeypatch.setattr(
        auth_routes,
        "register_user",
        fake_register_user,
    )

    app.dependency_overrides[get_db_session] = fake_db_session

    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "new@example.com",
                "full_name": "New User",
                "password": "StrongPassword123!",
                "organization_name": "Zohaib Labs",
                "organization_slug": "zohaib-labs",
            },
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "Organization slug already exists"}

    finally:
        app.dependency_overrides.clear()


def test_me_requires_authentication() -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code in {
        401,
        403,
    }


def test_mcp_token_requires_authentication() -> None:
    response = client.post(
        "/api/v1/auth/mcp-token",
    )

    assert response.status_code in {
        401,
        403,
    }


def test_authenticated_user_can_create_mcp_token() -> None:
    user_id = uuid.uuid4()

    async def fake_current_user() -> SimpleNamespace:
        return SimpleNamespace(
            id=user_id,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = fake_current_user

    try:
        response = client.post(
            "/api/v1/auth/mcp-token",
        )

        assert response.status_code == 200

        payload = response.json()

        assert isinstance(
            payload["access_token"],
            str,
        )

        assert payload["token_type"] == "bearer"

    finally:
        app.dependency_overrides.clear()
