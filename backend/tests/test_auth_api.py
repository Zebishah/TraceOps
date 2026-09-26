from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from ops_pilot.api.routes import auth as auth_routes
from ops_pilot.db.session import get_db_session
from ops_pilot.main import app
from ops_pilot.services.auth import (
    EmailAlreadyRegisteredError,
    OrganizationSlugAlreadyExistsError,
)

client = TestClient(app)


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
