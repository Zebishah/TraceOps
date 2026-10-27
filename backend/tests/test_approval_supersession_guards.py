import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    ApprovalDecisionConflictError,
)
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.schemas.incident_actions import IncidentActionProposal
from ops_pilot.services.approvals import (
    create_or_get_pending_approval,
)


def make_proposal() -> IncidentActionProposal:
    return IncidentActionProposal(
        requires_approval=True,
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        external_transaction_id="DEMO-CHARGE",
        amount=Decimal("100.00"),
        currency="USD",
        reason="Verified synthetic duplicate charge",
    )


def make_session(
    *,
    active: list[ApprovalRequest],
) -> tuple[AsyncSession, AsyncMock]:
    incident = Incident(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        title="Duplicate payment",
        description="Synthetic duplicate charge",
        status=IncidentStatus.AWAITING_APPROVAL,
    )

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    active_result = Mock()
    active_result.scalars.return_value.all.return_value = active

    session_mock = AsyncMock(spec=AsyncSession)
    session_mock.execute.side_effect = [
        incident_result,
        active_result,
    ]

    return cast(AsyncSession, session_mock), session_mock


def make_approval(
    *,
    thread_id: str,
    status: ApprovalStatus = ApprovalStatus.PENDING,
) -> ApprovalRequest:
    return ApprovalRequest(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        workflow_thread_id=thread_id,
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        action_payload={
            "external_transaction_id": "DEMO-CHARGE",
            "amount": "100.00",
            "currency": "USD",
        },
        reason="Synthetic duplicate review",
        status=status,
    )


@pytest.mark.asyncio
async def test_same_thread_reuses_matching_pending_approval() -> None:
    existing = make_approval(thread_id="thread-one")
    session, mock = make_session(active=[existing])

    result = await create_or_get_pending_approval(
        session=session,
        organization_id=existing.organization_id,
        incident_id=existing.incident_id,
        workflow_thread_id="thread-one",
        proposal=make_proposal(),
    )

    assert result is existing
    mock.add.assert_not_called()
    mock.commit.assert_not_awaited()
    mock.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_thread_cannot_reuse_pending_approval() -> None:
    existing = make_approval(thread_id="original-thread")
    session, mock = make_session(active=[existing])

    with pytest.raises(ApprovalDecisionConflictError):
        await create_or_get_pending_approval(
            session=session,
            organization_id=existing.organization_id,
            incident_id=existing.incident_id,
            workflow_thread_id="different-thread",
            proposal=make_proposal(),
        )

    mock.add.assert_not_called()
    mock.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_request_blocks_new_approval() -> None:
    existing = make_approval(
        thread_id="original-thread",
        status=ApprovalStatus.APPROVED,
    )
    session, mock = make_session(active=[existing])

    with pytest.raises(ApprovalDecisionConflictError):
        await create_or_get_pending_approval(
            session=session,
            organization_id=existing.organization_id,
            incident_id=existing.incident_id,
            workflow_thread_id="different-thread",
            proposal=make_proposal(),
        )

    mock.add.assert_not_called()
    mock.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_active_records_fail_closed() -> None:
    first = make_approval(thread_id="thread-one")
    second = make_approval(thread_id="thread-two")

    session, mock = make_session(active=[first, second])

    with pytest.raises(ApprovalDecisionConflictError):
        await create_or_get_pending_approval(
            session=session,
            organization_id=first.organization_id,
            incident_id=first.incident_id,
            workflow_thread_id="thread-one",
            proposal=make_proposal(),
        )

    mock.add.assert_not_called()
    mock.commit.assert_not_awaited()


def test_supersession_keeps_human_approval_metadata() -> None:
    approval = make_approval(
        thread_id="original-thread",
        status=ApprovalStatus.APPROVED,
    )

    reviewer_id = uuid.uuid4()
    decision_time = datetime.now(UTC)
    keeper_id = uuid.uuid4()

    approval.decided_by_user_id = reviewer_id
    approval.decided_at = decision_time

    approval.status = ApprovalStatus.SUPERSEDED
    approval.superseded_by_approval_id = keeper_id
    approval.superseded_at = datetime.now(UTC)
    approval.supersession_reason = "Duplicate approval superseded administratively"

    assert approval.status == ApprovalStatus.SUPERSEDED
    assert approval.decided_by_user_id == reviewer_id
    assert approval.decided_at == decision_time
    assert approval.executed_at is None
    assert approval.superseded_by_approval_id == keeper_id
    assert approval.supersession_reason
