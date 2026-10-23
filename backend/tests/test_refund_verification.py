import uuid
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.approval import (
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.incident import (
    Incident,
    IncidentStatus,
)
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.schemas.action_execution import RefundExecutionResult
from ops_pilot.services.refund_verification import (
    verify_refund_execution,
)


def make_verification_fixture() -> tuple[
    AsyncSession,
    AsyncMock,
    Incident,
    uuid.UUID,
    uuid.UUID,
    uuid.UUID,
    RefundExecutionResult,
]:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    source_id = uuid.uuid4()

    approval = Mock(spec=ApprovalRequest)
    approval.status = ApprovalStatus.EXECUTED

    source = Mock(spec=PaymentTransaction)
    source.id = source_id
    source.transaction_type = PaymentTransactionType.CHARGE
    source.status = PaymentTransactionStatus.REFUNDED
    source.amount = Decimal("12000.00")
    source.currency = "PKR"

    refund = Mock(spec=PaymentTransaction)
    refund.status = PaymentTransactionStatus.SUCCEEDED
    refund.amount = Decimal("12000.00")
    refund.currency = "PKR"

    incident = Incident(
        id=incident_id,
        organization_id=organization_id,
        created_by_user_id=uuid.uuid4(),
        title="Duplicate payment",
        description="Refund verification test",
        status=IncidentStatus.INVESTIGATING,
    )

    session_mock = AsyncMock(spec=AsyncSession)

    results = []
    for value in (approval, source, refund, incident):
        result = Mock()
        result.scalar_one_or_none.return_value = value
        results.append(result)

    session_mock.execute.side_effect = results

    execution = RefundExecutionResult(
        source_transaction_id="TXN-123",
        refund_transaction_id=f"refund-{approval_id}",
        amount=Decimal("12000.00"),
        currency="PKR",
        already_executed=False,
    )

    return (
        cast(AsyncSession, session_mock),
        session_mock,
        incident,
        organization_id,
        incident_id,
        approval_id,
        execution,
    )


@pytest.mark.asyncio
async def test_refund_verification_commits_successfully() -> None:
    (
        session,
        session_mock,
        incident,
        organization_id,
        incident_id,
        approval_id,
        execution,
    ) = make_verification_fixture()

    await verify_refund_execution(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_id,
        execution=execution,
    )

    assert incident.status == IncidentStatus.RESOLVED

    session_mock.commit.assert_awaited_once()
    session_mock.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_refund_verification_rolls_back_on_commit_failure() -> None:
    (
        session,
        session_mock,
        incident,
        organization_id,
        incident_id,
        approval_id,
        execution,
    ) = make_verification_fixture()

    session_mock.commit.side_effect = RuntimeError("Database commit failed")

    with pytest.raises(
        RuntimeError,
        match="Database commit failed",
    ):
        await verify_refund_execution(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            approval_request_id=approval_id,
            execution=execution,
        )

    session_mock.commit.assert_awaited_once()
    session_mock.rollback.assert_awaited_once()

    # The in-memory ORM object was assigned RESOLVED before
    # commit. This mocked test verifies rollback was invoked;
    # database atomicity requires a real integration test.
    assert incident.status == IncidentStatus.RESOLVED
