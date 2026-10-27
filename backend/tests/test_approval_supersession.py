from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ops_pilot.models.approval import (
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.schemas.approvals import ApprovalResponse


def test_superseded_is_distinct_from_rejection() -> None:
    assert ApprovalStatus.SUPERSEDED != ApprovalStatus.REJECTED
    assert ApprovalStatus.SUPERSEDED != ApprovalStatus.FAILED


def test_supersession_preserves_original_reviewer() -> None:
    reviewer_id = uuid4()
    keeper_id = uuid4()
    now = datetime.now(UTC)

    approval = ApprovalRequest(
        id=uuid4(),
        organization_id=uuid4(),
        incident_id=uuid4(),
        workflow_thread_id="original-review",
        action_type="refund_transaction",
        action_payload={
            "external_transaction_id": "DEMO-CHARGE",
            "amount": "100.00",
            "currency": "USD",
        },
        reason="Original duplicate payment review",
        status=ApprovalStatus.APPROVED,
        decided_by_user_id=reviewer_id,
        decided_at=now,
    )

    approval.status = ApprovalStatus.SUPERSEDED
    approval.superseded_by_approval_id = keeper_id
    approval.superseded_at = now

    assert approval.status == ApprovalStatus.SUPERSEDED
    assert approval.decided_by_user_id == reviewer_id
    assert approval.decided_at == now
    assert approval.executed_at is None
    assert approval.superseded_by_approval_id == keeper_id


def test_approval_response_supports_supersession() -> None:
    now = datetime.now(UTC)

    approval = ApprovalRequest(
        id=uuid4(),
        organization_id=uuid4(),
        incident_id=uuid4(),
        workflow_thread_id="superseded-test",
        action_type="refund_transaction",
        action_payload={
            "external_transaction_id": "DEMO-CHARGE",
            "amount": "100.00",
            "currency": "USD",
        },
        reason="Duplicate approval",
        status=ApprovalStatus.SUPERSEDED,
        superseded_by_approval_id=uuid4(),
        superseded_at=now,
    )

    approval.created_at = now
    approval.updated_at = now

    response = ApprovalResponse.model_validate(approval)

    assert response.status == ApprovalStatus.SUPERSEDED
    assert response.superseded_by_approval_id == approval.superseded_by_approval_id
    assert response.superseded_at == now


@pytest.mark.parametrize(
    "status",
    [
        ApprovalStatus.PENDING,
        ApprovalStatus.APPROVED,
        ApprovalStatus.EXECUTED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.FAILED,
        ApprovalStatus.SUPERSEDED,
    ],
)
def test_approval_status_serializes(
    status: ApprovalStatus,
) -> None:
    assert isinstance(status.value, str)
    assert status.value
