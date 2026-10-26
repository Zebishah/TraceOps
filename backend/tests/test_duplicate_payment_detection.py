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
        tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
        arguments={
            "order_id": "ORD-123",
        },
        success=True,
        content=json.dumps(
            [
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "payment_instrument_fingerprint": "test-instrument-42",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-08T10:00:00Z",
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "payment_instrument_fingerprint": "test-instrument-42",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-08T10:01:00Z",
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


def test_identical_transaction_ids_are_not_two_charges() -> None:
    result = ToolExecutionResult(
        call_id="same-id",
        tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
        arguments={"order_id": "ORD-123"},
        success=True,
        content=json.dumps(
            [
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "50.00",
                    "currency": "USD",
                    "status": "succeeded",
                    "processed_at": "2026-10-08T10:00:00Z",
                },
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "50.00",
                    "currency": "USD",
                    "status": "succeeded",
                    "processed_at": "2026-10-08T10:01:00Z",
                },
            ]
        ),
    )
    assert detect_duplicate_payment_candidate(tool_results=[result]) is None


def test_fractional_seconds_over_window_are_not_rounded_down() -> None:
    result = ToolExecutionResult(
        call_id="fractional",
        tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
        arguments={"order_id": "ORD-123"},
        success=True,
        content=json.dumps(
            [
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "50.00",
                    "currency": "USD",
                    "status": "succeeded",
                    "processed_at": "2026-10-08T10:00:00Z",
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "50.00",
                    "currency": "USD",
                    "status": "succeeded",
                    "processed_at": "2026-10-08T10:05:00.001Z",
                },
            ]
        ),
    )
    assert detect_duplicate_payment_candidate(tool_results=[result]) is None


def test_rejects_missing_payment_fingerprint() -> None:
    payments = [
        {
            "external_transaction_id": "TXN-A",
            "provider": "stripe",
            "payment_instrument_fingerprint": None,
            "transaction_type": "charge",
            "amount": "50.00",
            "currency": "USD",
            "status": "succeeded",
            "processed_at": "2026-10-08T10:00:00Z",
        },
        {
            "external_transaction_id": "TXN-B",
            "provider": "stripe",
            "payment_instrument_fingerprint": None,
            "transaction_type": "charge",
            "amount": "50.00",
            "currency": "USD",
            "status": "succeeded",
            "processed_at": "2026-10-08T10:01:00Z",
        },
    ]

    result = ToolExecutionResult(
        tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
        arguments={"order_id": "ORD-123"},
        success=True,
        content=json.dumps(payments),
    )

    assert detect_duplicate_payment_candidate(tool_results=[result]) is None


def test_rejects_different_payment_fingerprints() -> None:
    payments = [
        {
            "external_transaction_id": "TXN-A",
            "provider": "stripe",
            "payment_instrument_fingerprint": "instrument-one",
            "transaction_type": "charge",
            "amount": "50.00",
            "currency": "USD",
            "status": "succeeded",
            "processed_at": "2026-10-08T10:00:00Z",
        },
        {
            "external_transaction_id": "TXN-B",
            "provider": "stripe",
            "payment_instrument_fingerprint": "instrument-two",
            "transaction_type": "charge",
            "amount": "50.00",
            "currency": "USD",
            "status": "succeeded",
            "processed_at": "2026-10-08T10:01:00Z",
        },
    ]

    result = ToolExecutionResult(
        tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
        arguments={"order_id": "ORD-123"},
        success=True,
        content=json.dumps(payments),
    )

    assert detect_duplicate_payment_candidate(tool_results=[result]) is None
