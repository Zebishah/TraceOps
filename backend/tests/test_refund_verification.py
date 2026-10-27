import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import ApprovalExecutionError
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.schemas.action_execution import RefundExecutionResult
from ops_pilot.services.refund_verification import verify_refund_execution


def make_verification_fixture() -> tuple[
    AsyncSession,
    AsyncMock,
    ApprovalRequest,
    PaymentTransaction,
    PaymentTransaction,
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
    order_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()
    now = datetime.now(UTC)

    approval = ApprovalRequest(
        id=approval_id,
        organization_id=organization_id,
        incident_id=incident_id,
        workflow_thread_id="refund-verification-test",
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        action_payload={
            "external_transaction_id": "TXN-123",
            "amount": "12000.00",
            "currency": "PKR",
        },
        reason="Verified duplicate payment",
        status=ApprovalStatus.EXECUTED,
        decided_by_user_id=reviewer_id,
        decided_at=now,
        executed_at=now,
    )

    source = PaymentTransaction(
        id=source_id,
        organization_id=organization_id,
        order_id=order_id,
        external_transaction_id="TXN-123",
        provider="demo_gateway",
        transaction_type=PaymentTransactionType.CHARGE,
        amount=Decimal("12000.00"),
        currency="PKR",
        status=PaymentTransactionStatus.REFUNDED,
        processed_at=now,
    )

    refund = PaymentTransaction(
        id=uuid.uuid4(),
        organization_id=organization_id,
        order_id=order_id,
        source_transaction_id=source_id,
        external_transaction_id=f"refund-{approval_id}",
        provider="demo_gateway",
        transaction_type=PaymentTransactionType.REFUND,
        amount=Decimal("12000.00"),
        currency="PKR",
        status=PaymentTransactionStatus.SUCCEEDED,
        processed_at=now,
    )

    incident = Incident(
        id=incident_id,
        organization_id=organization_id,
        created_by_user_id=uuid.uuid4(),
        title="Duplicate payment",
        description="Refund verification test",
        status=IncidentStatus.AWAITING_APPROVAL,
    )

    execution = RefundExecutionResult(
        source_transaction_id="TXN-123",
        refund_transaction_id=f"refund-{approval_id}",
        amount=Decimal("12000.00"),
        currency="PKR",
        already_executed=False,
    )

    session_mock = AsyncMock(spec=AsyncSession)

    def make_result(value: object) -> Mock:
        result = Mock()
        result.scalar_one_or_none.return_value = value
        return result

    # The verifier queries in this exact order:
    # incident -> approval -> source -> refund.
    session_mock.execute.side_effect = [
        make_result(incident),
        make_result(approval),
        make_result(source),
        make_result(refund),
    ]

    return (
        cast(AsyncSession, session_mock),
        session_mock,
        approval,
        source,
        refund,
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
        approval,
        source,
        refund,
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

    assert approval.status == ApprovalStatus.EXECUTED
    assert source.status == PaymentTransactionStatus.REFUNDED
    assert refund.status == PaymentTransactionStatus.SUCCEEDED

    assert incident.status == IncidentStatus.RESOLVED
    assert incident.resolved_at is not None
    assert incident.resolved_by_user_id == approval.decided_by_user_id

    assert incident.resolution_reason is not None
    assert "internal refund ledger" in incident.resolution_reason.lower()
    assert "no external payment provider refund" in incident.resolution_reason.lower()

    session_mock.commit.assert_awaited_once()
    session_mock.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_refund_verification_rolls_back_on_commit_failure() -> None:
    (
        session,
        session_mock,
        approval,
        source,
        refund,
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

    # Mocked ORM objects retain in-memory assignments.
    # Database rollback correctness needs the real PG test.
    assert incident.status == IncidentStatus.RESOLVED


@pytest.mark.parametrize(
    ("record", "field", "value"),
    [
        ("approval", "status", ApprovalStatus.PENDING),
        ("approval", "decided_by_user_id", None),
        ("approval", "decided_at", None),
        ("approval", "executed_at", None),
        ("approval", "action_type", None),
        ("source", "amount", Decimal("100.00")),
        ("source", "currency", "USD"),
        ("source", "provider", "other_gateway"),
        ("refund", "amount", Decimal("100.00")),
        ("refund", "currency", "USD"),
        ("refund", "order_id", uuid.UUID(int=2)),
        ("refund", "source_transaction_id", uuid.UUID(int=3)),
        ("refund", "provider", "other_gateway"),
        ("refund", "organization_id", uuid.UUID(int=4)),
        (
            "refund",
            "status",
            PaymentTransactionStatus.FAILED,
        ),
    ],
)
@pytest.mark.asyncio
async def test_inconsistent_records_never_resolve_incident(
    record: str,
    field: str,
    value: object,
) -> None:
    (
        session,
        session_mock,
        approval,
        source,
        refund,
        incident,
        organization_id,
        incident_id,
        approval_id,
        execution,
    ) = make_verification_fixture()

    records = {
        "approval": approval,
        "source": source,
        "refund": refund,
    }

    setattr(records[record], field, value)

    # Changing source.provider alone does not violate the
    # canonical validator unless the refund differs too.
    # Every test here must represent a real mismatch.
    if record == "source" and field == "provider":
        assert source.provider != refund.provider

    with pytest.raises(ApprovalExecutionError):
        await verify_refund_execution(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            approval_request_id=approval_id,
            execution=execution,
        )

    assert incident.status == IncidentStatus.AWAITING_APPROVAL
    session_mock.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("external_transaction_id", "WRONG-TXN"),
        ("amount", "9999.00"),
        ("currency", "USD"),
        ("amount", "NaN"),
        ("amount", "-1"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_approval_payload_is_rejected(
    field: str,
    value: str,
) -> None:
    (
        session,
        session_mock,
        approval,
        source,
        refund,
        incident,
        organization_id,
        incident_id,
        approval_id,
        execution,
    ) = make_verification_fixture()

    approval.action_payload = {
        **approval.action_payload,
        field: value,
    }

    with pytest.raises(ApprovalExecutionError):
        await verify_refund_execution(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            approval_request_id=approval_id,
            execution=execution,
        )

    assert incident.status == IncidentStatus.AWAITING_APPROVAL
    session_mock.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_transaction_id", "WRONG-TXN"),
        ("refund_transaction_id", "WRONG-REFUND"),
        ("amount", Decimal("1.00")),
        ("currency", "USD"),
    ],
)
@pytest.mark.asyncio
async def test_mismatched_execution_result_is_rejected(
    field: str,
    value: object,
) -> None:
    (
        session,
        session_mock,
        approval,
        source,
        refund,
        incident,
        organization_id,
        incident_id,
        approval_id,
        execution,
    ) = make_verification_fixture()

    invalid_execution = execution.model_copy(
        update={field: value},
    )

    with pytest.raises(ApprovalExecutionError):
        await verify_refund_execution(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            approval_request_id=approval_id,
            execution=invalid_execution,
        )

    assert incident.status == IncidentStatus.AWAITING_APPROVAL
    session_mock.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotent_verification_preserves_resolution_metadata() -> None:
    (
        session,
        session_mock,
        approval,
        source,
        refund,
        incident,
        organization_id,
        incident_id,
        approval_id,
        execution,
    ) = make_verification_fixture()

    original_resolved_at = datetime.now(UTC)

    incident.status = IncidentStatus.RESOLVED
    incident.resolved_by_user_id = approval.decided_by_user_id
    incident.resolved_at = original_resolved_at
    incident.resolution_reason = (
        "Approved internal refund ledger entry recorded. "
        "No external payment provider refund was initiated or confirmed."
    )

    await verify_refund_execution(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_id,
        execution=execution,
    )

    assert incident.resolved_at == original_resolved_at
    session_mock.commit.assert_not_awaited()
    session_mock.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_previous_manual_resolution_is_not_overwritten() -> None:
    (
        session,
        session_mock,
        approval,
        source,
        refund,
        incident,
        organization_id,
        incident_id,
        approval_id,
        execution,
    ) = make_verification_fixture()

    incident.status = IncidentStatus.RESOLVED
    incident.resolved_by_user_id = uuid.uuid4()
    incident.resolved_at = datetime.now(UTC)
    incident.resolution_reason = "Manually resolved by reviewer"

    with pytest.raises(
        ApprovalExecutionError,
        match="Existing incident resolution is inconsistent",
    ):
        await verify_refund_execution(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            approval_request_id=approval_id,
            execution=execution,
        )

    session_mock.commit.assert_not_awaited()
