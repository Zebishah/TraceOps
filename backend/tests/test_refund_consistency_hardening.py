"""Regression tests for already-recorded refund consistency."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ops_pilot.core.exceptions import ApprovalExecutionError
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.services.refund_execution import (
    validate_existing_refund,
)


def records():
    organization_id = uuid.uuid4()
    source_id = uuid.uuid4()
    order_id = uuid.uuid4()

    approval = ApprovalRequest(
        id=uuid.uuid4(),
        organization_id=organization_id,
        incident_id=uuid.uuid4(),
        workflow_thread_id="test-refund-consistency",
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        action_payload={
            "external_transaction_id": "CHARGE-123",
            "amount": "100.00",
            "currency": "USD",
        },
        reason="Synthetic test",
        status=ApprovalStatus.EXECUTED,
    )

    source = PaymentTransaction(
        id=source_id,
        organization_id=organization_id,
        order_id=order_id,
        external_transaction_id="CHARGE-123",
        provider="stripe",
        transaction_type=PaymentTransactionType.CHARGE,
        amount=Decimal("100.00"),
        currency="USD",
        status=PaymentTransactionStatus.REFUNDED,
        processed_at=datetime.now(UTC),
    )

    refund = PaymentTransaction(
        id=uuid.uuid4(),
        organization_id=organization_id,
        order_id=order_id,
        source_transaction_id=source_id,
        external_transaction_id="REFUND-123",
        provider="stripe",
        transaction_type=PaymentTransactionType.REFUND,
        amount=Decimal("100.00"),
        currency="USD",
        status=PaymentTransactionStatus.SUCCEEDED,
        processed_at=datetime.now(UTC),
    )

    return approval, source, refund


def test_valid_existing_refund():
    approval, source, refund = records()

    validate_existing_refund(
        approval=approval,
        source=source,
        refund=refund,
    )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("status", PaymentTransactionStatus.FAILED),
        ("amount", Decimal("99.00")),
        ("currency", "PKR"),
        ("order_id", uuid.UUID(int=1)),
        ("provider", "wrong-provider"),
        ("source_transaction_id", uuid.UUID(int=2)),
        ("organization_id", uuid.UUID(int=3)),
    ],
)
def test_inconsistent_refund_is_rejected(field, bad_value):
    approval, source, refund = records()
    setattr(refund, field, bad_value)

    with pytest.raises(
        ApprovalExecutionError,
        match="inconsistent",
    ):
        validate_existing_refund(
            approval=approval,
            source=source,
            refund=refund,
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("external_transaction_id", "WRONG-CHARGE"),
        ("amount", "200.00"),
        ("currency", "PKR"),
        ("amount", "NaN"),
    ],
)
def test_mismatched_approval_is_rejected(field, bad_value):
    approval, source, refund = records()
    approval.action_payload = {
        **approval.action_payload,
        field: bad_value,
    }

    with pytest.raises(ApprovalExecutionError):
        validate_existing_refund(
            approval=approval,
            source=source,
            refund=refund,
        )
