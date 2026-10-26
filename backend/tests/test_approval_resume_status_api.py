"""Authorization and behavior tests for approval recovery status."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from ops_pilot.api.dependencies import (
    get_current_membership,
    get_current_user,
)
from ops_pilot.api.routes import incidents as incident_routes
from ops_pilot.db.session import get_db_session
from ops_pilot.main import app
from ops_pilot.models.membership import MembershipRole
from ops_pilot.schemas.approval_resume_status import (
    ApprovalResumeStatusResponse,
)

client = TestClient(app)

ORG_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()
APPROVAL_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
USER_ID = uuid.uuid4()

PATH = (
    f"/api/v1/organizations/{ORG_ID}/incidents/{INCIDENT_ID}/approvals/{APPROVAL_ID}/resume-status"
)


def set_dependencies(role: MembershipRole) -> None:
    async def current_user():
        return SimpleNamespace(id=USER_ID)

    async def current_membership():
        return SimpleNamespace(
            organization_id=ORG_ID,
            user_id=USER_ID,
            role=role,
        )

    async def database_session():
        return AsyncMock()

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_current_membership] = current_membership
    app.dependency_overrides[get_db_session] = database_session


def make_response() -> ApprovalResumeStatusResponse:
    return ApprovalResumeStatusResponse(
        job_id=JOB_ID,
        approval_request_id=APPROVAL_ID,
        incident_id=INCIDENT_ID,
        status="failed",
        attempts=5,
        max_attempts=5,
        quarantined=True,
        next_attempt_at=None,
        lease_expires_at=None,
        completed_at=None,
    )


@pytest.mark.parametrize(
    "role",
    [
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.REVIEWER,
        MembershipRole.OPERATOR,
        MembershipRole.VIEWER,
    ],
)
def test_members_can_read_resume_status(
    monkeypatch: pytest.MonkeyPatch,
    role: MembershipRole,
) -> None:
    lookup = AsyncMock(return_value=make_response())

    monkeypatch.setattr(
        incident_routes,
        "get_approval_resume_status",
        lookup,
    )

    set_dependencies(role)

    try:
        response = client.get(PATH)

        assert response.status_code == 200

        body = response.json()

        assert body["status"] == "failed"
        assert body["attempts"] == 5
        assert body["max_attempts"] == 5
        assert body["quarantined"] is True
        assert body["job_id"] == str(JOB_ID)
        assert "last_error" not in body

        lookup.assert_awaited_once()

        kwargs = lookup.await_args.kwargs

        assert kwargs["organization_id"] == ORG_ID
        assert kwargs["incident_id"] == INCIDENT_ID
        assert kwargs["approval_request_id"] == APPROVAL_ID

    finally:
        app.dependency_overrides.clear()


def test_missing_job_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = AsyncMock(return_value=None)

    monkeypatch.setattr(
        incident_routes,
        "get_approval_resume_status",
        lookup,
    )

    set_dependencies(MembershipRole.VIEWER)

    try:
        response = client.get(PATH)

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Approval recovery job not found",
        }
    finally:
        app.dependency_overrides.clear()


def test_status_endpoint_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = AsyncMock(return_value=make_response())

    monkeypatch.setattr(
        incident_routes,
        "get_approval_resume_status",
        lookup,
    )

    set_dependencies(MembershipRole.REVIEWER)

    try:
        response = client.get(PATH)

        assert response.status_code == 200
        lookup.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
