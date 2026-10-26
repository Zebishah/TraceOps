import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from ops_pilot.api.dependencies import (
    get_current_membership,
    get_current_user,
)
from ops_pilot.api.routes import incidents as incident_routes
from ops_pilot.db.session import get_db_session
from ops_pilot.main import app
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.models.membership import MembershipRole
from ops_pilot.services.incident_resolution import (
    IncidentResolutionConflict,
    IncidentResolutionNotFound,
)

client = TestClient(app)

ORGANIZATION_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()

URL = f"/api/v1/organizations/{ORGANIZATION_ID}/incidents/{INCIDENT_ID}/resolve-no-action"

VALID_PAYLOAD = {"reason": "Verified that no refund is required."}


def make_incident():
    now = datetime.now(UTC)

    return SimpleNamespace(
        id=INCIDENT_ID,
        organization_id=ORGANIZATION_ID,
        created_by_user_id=USER_ID,
        subject_customer_id=None,
        title="Payment investigation",
        description="Payment verification completed.",
        status=IncidentStatus.RESOLVED,
        category="payment",
        priority=None,
        resolved_by_user_id=USER_ID,
        resolution_reason=VALID_PAYLOAD["reason"],
        resolved_at=now,
        created_at=now,
        updated_at=now,
    )


def authenticate(role: MembershipRole):
    async def fake_user():
        return SimpleNamespace(id=USER_ID)

    async def fake_membership():
        return SimpleNamespace(
            organization_id=ORGANIZATION_ID,
            user_id=USER_ID,
            role=role,
        )

    async def fake_session():
        return AsyncMock()

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_current_membership] = fake_membership
    app.dependency_overrides[get_db_session] = fake_session


@pytest.mark.parametrize(
    "role",
    [
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.REVIEWER,
    ],
)
def test_allowed_roles_can_resolve_incident(monkeypatch, role):
    service = AsyncMock(return_value=make_incident())
    invalidate = AsyncMock()

    monkeypatch.setattr(
        incident_routes,
        "resolve_incident_without_action",
        service,
    )
    monkeypatch.setattr(
        incident_routes,
        "invalidate_incident_cache",
        invalidate,
    )

    authenticate(role)

    try:
        response = client.post(URL, json=VALID_PAYLOAD)

        assert response.status_code == 200
        assert response.json()["status"] == "resolved"
        assert response.json()["resolved_by_user_id"] == str(USER_ID)
        assert response.json()["resolution_reason"] == VALID_PAYLOAD["reason"]

        service.assert_awaited_once()
        invalidate.assert_awaited_once()

    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "role",
    [
        MembershipRole.OPERATOR,
        MembershipRole.VIEWER,
    ],
)
def test_unauthorized_roles_cannot_resolve(monkeypatch, role):
    service = AsyncMock()

    monkeypatch.setattr(
        incident_routes,
        "resolve_incident_without_action",
        service,
    )

    authenticate(role)

    try:
        response = client.post(URL, json=VALID_PAYLOAD)

        assert response.status_code == 403
        service.assert_not_awaited()

    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "reason",
    ["", "short", "   "],
)
def test_invalid_reason_returns_422(reason):
    authenticate(MembershipRole.REVIEWER)

    try:
        response = client.post(
            URL,
            json={"reason": reason},
        )

        assert response.status_code == 422

    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            IncidentResolutionConflict("Incident already resolved"),
            409,
        ),
        (
            IncidentResolutionConflict("Blocking approval exists"),
            409,
        ),
        (
            IncidentResolutionNotFound("Incident not found"),
            404,
        ),
    ],
)
def test_resolution_errors_are_mapped_correctly(
    monkeypatch,
    error,
    expected_status,
):
    service = AsyncMock(side_effect=error)

    monkeypatch.setattr(
        incident_routes,
        "resolve_incident_without_action",
        service,
    )

    authenticate(MembershipRole.REVIEWER)

    try:
        response = client.post(URL, json=VALID_PAYLOAD)

        assert response.status_code == expected_status

    finally:
        app.dependency_overrides.clear()


def test_nonmember_cannot_resolve_incident(monkeypatch):
    service = AsyncMock()

    monkeypatch.setattr(
        incident_routes,
        "resolve_incident_without_action",
        service,
    )

    fake_session = AsyncMock()
    result = Mock()
    result.scalar_one_or_none.return_value = None
    fake_session.execute.return_value = result

    async def override_session():
        return fake_session

    async def override_user():
        return SimpleNamespace(id=USER_ID)

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    try:
        response = client.post(URL, json=VALID_PAYLOAD)

        assert response.status_code == 403
        service.assert_not_awaited()

    finally:
        app.dependency_overrides.clear()
