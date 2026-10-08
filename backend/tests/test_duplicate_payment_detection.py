import json

from ops_pilot.services.duplicate_payment_detection import (
    detect_duplicate_payment_candidate,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolExecutionResult,
)


def test_detects_later_matching_charge_as_duplicate() -> None:
    result = ToolExecutionResult(
        call_id="test",
        tool_name=(OperationalToolName.LIST_ORDER_PAYMENTS),
        arguments={
            "order_id": "ORD-123",
        },
        success=True,
        content=json.dumps(
            [
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": ("2026-10-08T10:00:00Z"),
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": ("2026-10-08T10:01:00Z"),
                },
            ]
        ),
    )

    candidate = detect_duplicate_payment_candidate(
        tool_results=[result],
    )

    assert candidate is not None
    assert candidate.original_transaction_id == "TXN-A"
    assert candidate.duplicate_transaction_id == "TXN-B"
    assert candidate.seconds_apart == 60


def test_does_not_detect_different_amounts() -> None:
    result = ToolExecutionResult(
        call_id="test",
        tool_name=(OperationalToolName.LIST_ORDER_PAYMENTS),
        arguments={
            "order_id": "ORD-123",
        },
        success=True,
        content=json.dumps(
            [
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": ("2026-10-08T10:00:00Z"),
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "15000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": ("2026-10-08T10:01:00Z"),
                },
            ]
        ),
    )

    candidate = detect_duplicate_payment_candidate(
        tool_results=[result],
    )

    assert candidate is None


def test_does_not_detect_payments_too_far_apart() -> None:
    result = ToolExecutionResult(
        call_id="test",
        tool_name=(OperationalToolName.LIST_ORDER_PAYMENTS),
        arguments={
            "order_id": "ORD-123",
        },
        success=True,
        content=json.dumps(
            [
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": ("2026-10-08T10:00:00Z"),
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": ("2026-10-08T11:00:00Z"),
                },
            ]
        ),
    )

    candidate = detect_duplicate_payment_candidate(
        tool_results=[result],
    )

    assert candidate is None
