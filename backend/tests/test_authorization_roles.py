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
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalStatus,
)
from ops_pilot.models.membership import (
    MembershipRole,
)

client = TestClient(app)

ORGANIZATION_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()
APPROVAL_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


async def fake_db_session() -> AsyncMock:
    return AsyncMock()


async def fake_current_user():
    return SimpleNamespace(
        id=USER_ID,
    )


def make_membership(
    role: MembershipRole,
):
    return SimpleNamespace(
        organization_id=ORGANIZATION_ID,
        user_id=USER_ID,
        role=role,
    )


def make_approval():
    now = datetime.now(UTC)

    return SimpleNamespace(
        id=APPROVAL_ID,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
        workflow_thread_id="thread-123",
        action_type=(ApprovalActionType.REFUND_TRANSACTION),
        action_payload={
            "external_transaction_id": "TXN-123",
            "amount": "12000.00",
            "currency": "PKR",
        },
        reason="Confirmed duplicate payment.",
        status=ApprovalStatus.APPROVED,
        decided_by_user_id=USER_ID,
        decision_comment="Approved",
        decided_at=now,
        executed_at=None,
        created_at=now,
        updated_at=now,
    )


def set_role_dependencies(
    role: MembershipRole,
) -> None:
    async def fake_membership():
        return make_membership(role)

    app.dependency_overrides[get_db_session] = fake_db_session

    app.dependency_overrides[get_current_user] = fake_current_user

    app.dependency_overrides[get_current_membership] = fake_membership


@pytest.mark.parametrize(
    "role",
    [
        MembershipRole.OPERATOR,
        MembershipRole.VIEWER,
    ],
)
def test_approval_decision_rejects_unauthorized_roles(
    monkeypatch: pytest.MonkeyPatch,
    role: MembershipRole,
) -> None:
    decide_mock = AsyncMock(return_value=make_approval())

    monkeypatch.setattr(
        incident_routes,
        "decide_and_resume_approval",
        decide_mock,
    )

    set_role_dependencies(role)

    try:
        response = client.post(
            (
                f"/api/v1/organizations/"
                f"{ORGANIZATION_ID}/incidents/"
                f"{INCIDENT_ID}/approvals/"
                f"{APPROVAL_ID}/decision"
            ),
            json={
                "approved": True,
                "comment": "approve",
            },
        )

        assert response.status_code == 403

        assert response.json() == {
            "detail": ("Approval decisions require reviewer, admin, or owner role"),
        }

        decide_mock.assert_not_awaited()

    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "role",
    [
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.REVIEWER,
    ],
)
def test_approval_decision_allows_authorized_roles(
    monkeypatch: pytest.MonkeyPatch,
    role: MembershipRole,
) -> None:
    approval = make_approval()

    decide_mock = AsyncMock(return_value=approval)

    monkeypatch.setattr(
        incident_routes,
        "decide_and_resume_approval",
        decide_mock,
    )

    set_role_dependencies(role)

    try:
        response = client.post(
            (
                f"/api/v1/organizations/"
                f"{ORGANIZATION_ID}/incidents/"
                f"{INCIDENT_ID}/approvals/"
                f"{APPROVAL_ID}/decision"
            ),
            json={
                "approved": True,
                "comment": "approve",
            },
        )

        assert response.status_code == 200

        body = response.json()

        assert body["id"] == str(APPROVAL_ID)

        assert body["status"] == "approved"

        decide_mock.assert_awaited_once()

        assert decide_mock.await_args is not None

        call_kwargs = decide_mock.await_args.kwargs

        assert call_kwargs["organization_id"] == ORGANIZATION_ID

        assert call_kwargs["incident_id"] == INCIDENT_ID

        assert call_kwargs["approval_request_id"] == APPROVAL_ID

        assert call_kwargs["decided_by_user_id"] == USER_ID

    finally:
        app.dependency_overrides.clear()


def test_approval_endpoint_requires_membership() -> None:
    fake_session = AsyncMock()

    membership_result = Mock()
    membership_result.scalar_one_or_none.return_value = None

    fake_session.execute.return_value = membership_result

    async def override_db_session():
        return fake_session

    app.dependency_overrides[get_db_session] = override_db_session

    app.dependency_overrides[get_current_user] = fake_current_user

    try:
        response = client.get(
            f"/api/v1/organizations/"
            f"{ORGANIZATION_ID}/incidents/"
            f"{INCIDENT_ID}/approvals/"
            f"{APPROVAL_ID}"
        )

        assert response.status_code == 403

        assert response.json() == {
            "detail": ("You do not have access to this organization"),
        }

    finally:
        app.dependency_overrides.clear()
