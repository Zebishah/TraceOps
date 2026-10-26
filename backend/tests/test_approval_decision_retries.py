"""Regression tests for idempotent human approval decisions."""

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.core.exceptions import ApprovalDecisionConflictError
from ops_pilot.models.approval import ApprovalStatus
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.schemas.approvals import ApprovalDecisionRequest
from ops_pilot.services.approvals import record_approval_decision


def make_session(
    *,
    approval_status: ApprovalStatus,
):
    reviewer_id = uuid.uuid4()
    decision_time = datetime.now(UTC)

    incident = SimpleNamespace(
        status=IncidentStatus.AWAITING_APPROVAL,
    )

    approval = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        status=approval_status,
        decided_by_user_id=reviewer_id,
        decision_comment="Original human decision",
        decided_at=decision_time,
        executed_at=(decision_time if approval_status == ApprovalStatus.EXECUTED else None),
    )

    session = AsyncMock()

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    approval_result = Mock()
    approval_result.scalar_one_or_none.return_value = approval

    session.execute.side_effect = [
        incident_result,
        approval_result,
    ]

    # No existing resume job: test its backfill.
    session.scalar.return_value = None
    session.add = Mock()

    return session, incident, approval


def submit_decision(
    *,
    session,
    approval,
    approved: bool,
):
    return asyncio.run(
        record_approval_decision(
            session=session,
            organization_id=approval.organization_id,
            incident_id=approval.incident_id,
            approval_request_id=approval.id,
            decided_by_user_id=uuid.uuid4(),
            payload=ApprovalDecisionRequest(
                approved=approved,
                comment="Repeated button click",
            ),
        )
    )


@pytest.mark.parametrize(
    ("existing_status", "approved"),
    [
        (ApprovalStatus.APPROVED, True),
        (ApprovalStatus.REJECTED, False),
        (ApprovalStatus.EXECUTED, True),
    ],
)
def test_identical_decision_retry_is_idempotent(
    existing_status: ApprovalStatus,
    approved: bool,
) -> None:
    session, incident, approval = make_session(
        approval_status=existing_status,
    )

    original_reviewer = approval.decided_by_user_id
    original_comment = approval.decision_comment
    original_time = approval.decided_at

    result = submit_decision(
        session=session,
        approval=approval,
        approved=approved,
    )

    assert result is approval
    assert approval.status == existing_status
    assert approval.decided_by_user_id == original_reviewer
    assert approval.decision_comment == original_comment
    assert approval.decided_at == original_time

    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(approval)
    session.rollback.assert_not_awaited()

    if existing_status == ApprovalStatus.EXECUTED:
        session.add.assert_not_called()
    else:
        session.add.assert_called_once()


@pytest.mark.parametrize(
    ("existing_status", "approved"),
    [
        (ApprovalStatus.APPROVED, False),
        (ApprovalStatus.REJECTED, True),
        (ApprovalStatus.EXECUTED, False),
    ],
)
def test_opposite_decision_is_rejected(
    existing_status: ApprovalStatus,
    approved: bool,
) -> None:
    session, incident, approval = make_session(
        approval_status=existing_status,
    )

    with pytest.raises(ApprovalDecisionConflictError):
        submit_decision(
            session=session,
            approval=approval,
            approved=approved,
        )

    assert approval.status == existing_status
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    session.add.assert_not_called()


def test_idempotent_retry_backfill_failure_rolls_back() -> None:
    session, incident, approval = make_session(
        approval_status=ApprovalStatus.APPROVED,
    )

    session.scalar.side_effect = RuntimeError("Database unavailable")

    with pytest.raises(RuntimeError, match="Database unavailable"):
        submit_decision(
            session=session,
            approval=approval,
            approved=True,
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
