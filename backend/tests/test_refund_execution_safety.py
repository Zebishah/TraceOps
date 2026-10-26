import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.core.exceptions import ApprovalExecutionError
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalStatus,
)
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.services.refund_execution import (
    execute_approved_refund,
)


def make_session(
    incident_status: IncidentStatus,
    approval_status: ApprovalStatus,
) -> AsyncMock:
    incident = SimpleNamespace(
        status=incident_status,
    )

    approval = SimpleNamespace(
        id=uuid.uuid4(),
        status=approval_status,
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        action_payload={
            "external_transaction_id": "charge-test-123",
            "amount": "100.00",
            "currency": "USD",
        },
        decided_by_user_id=uuid.uuid4(),
        decided_at=None,
    )

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    approval_result = Mock()
    approval_result.scalar_one_or_none.return_value = approval

    session = AsyncMock()
    session.execute.side_effect = [
        incident_result,
        approval_result,
    ]

    return session


def run_refund(session: AsyncMock) -> None:
    asyncio.run(
        execute_approved_refund(
            session=session,
            organization_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            approval_request_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
        )
    )


def test_resolved_incident_cannot_execute_refund() -> None:
    session = make_session(
        IncidentStatus.RESOLVED,
        ApprovalStatus.APPROVED,
    )

    with pytest.raises(
        ApprovalExecutionError,
        match="resolved incident",
    ):
        run_refund(session)

    session.commit.assert_not_awaited()
    session.add.assert_not_called()
    session.rollback.assert_awaited_once()
    assert session.execute.await_count == 2


def test_investigating_incident_cannot_execute_refund() -> None:
    session = make_session(
        IncidentStatus.INVESTIGATING,
        ApprovalStatus.APPROVED,
    )

    with pytest.raises(
        ApprovalExecutionError,
        match="not awaiting approved action",
    ):
        run_refund(session)

    session.commit.assert_not_awaited()
    session.add.assert_not_called()


def test_pending_approval_cannot_execute_refund() -> None:
    session = make_session(
        IncidentStatus.AWAITING_APPROVAL,
        ApprovalStatus.PENDING,
    )

    with pytest.raises(
        ApprovalExecutionError,
        match="requires an approved request",
    ):
        run_refund(session)

    session.commit.assert_not_awaited()
    session.add.assert_not_called()


def test_missing_incident_blocks_refund() -> None:
    session = AsyncMock()

    result = Mock()
    result.scalar_one_or_none.return_value = None

    session.execute.return_value = result

    with pytest.raises(
        ApprovalExecutionError,
        match="Incident not found",
    ):
        run_refund(session)

    assert session.execute.await_count == 1
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
