import json
from decimal import Decimal

import pytest

from ops_pilot.services.duplicate_payment_detection import (
    detect_duplicate_payment_candidate,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolExecutionResult,
)


def order_data(
    *,
    order_id: str = "ORD-123",
    total: str = "100.00",
    currency: str = "USD",
    status: str = "paid",
) -> dict[str, object]:
    return {
        "external_order_id": order_id,
        "product_name": "Demo product",
        "total_amount": total,
        "currency": currency,
        "status": status,
        "ordered_at": "2026-10-08T09:00:00Z",
    }


def payment_data(
    transaction_id: str,
    timestamp: str,
    *,
    amount: str = "100.00",
    currency: str = "USD",
    provider: str = "demo_gateway",
    fingerprint: str | None = "demo-card-token",
    status: str = "succeeded",
    transaction_type: str = "charge",
) -> dict[str, object]:
    return {
        "external_transaction_id": transaction_id,
        "provider": provider,
        "payment_instrument_fingerprint": fingerprint,
        "transaction_type": transaction_type,
        "amount": amount,
        "currency": currency,
        "status": status,
        "processed_at": timestamp,
    }


def build_results(
    *,
    payments: list[dict[str, object]],
    orders: list[dict[str, object]] | None = None,
    order_id: str = "ORD-123",
) -> list[ToolExecutionResult]:
    results: list[ToolExecutionResult] = []

    if orders is not None:
        results.append(
            ToolExecutionResult(
                call_id="orders",
                tool_name=OperationalToolName.LIST_CUSTOMER_ORDERS,
                arguments={"limit": 10},
                success=True,
                content=json.dumps(orders),
            )
        )

    results.append(
        ToolExecutionResult(
            call_id="payments",
            tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
            arguments={"order_id": order_id},
            success=True,
            content=json.dumps(payments),
        )
    )

    return results


def matching_payments() -> list[dict[str, object]]:
    return [
        payment_data(
            "TXN-A",
            "2026-10-08T10:00:00Z",
        ),
        payment_data(
            "TXN-B",
            "2026-10-08T10:01:00Z",
        ),
    ]


def test_detects_verified_full_order_duplicate() -> None:
    candidate = detect_duplicate_payment_candidate(
        tool_results=build_results(
            payments=matching_payments(),
            orders=[order_data()],
        )
    )

    assert candidate is not None
    assert candidate.order_id == "ORD-123"
    assert candidate.original_transaction_id == "TXN-A"
    assert candidate.duplicate_transaction_id == "TXN-B"
    assert candidate.amount == Decimal("100.00")
    assert candidate.provider == "demo_gateway"
    assert candidate.seconds_apart == 60


def test_missing_order_evidence_rejects_candidate() -> None:
    assert (
        detect_duplicate_payment_candidate(
            tool_results=build_results(
                payments=matching_payments(),
                orders=None,
            )
        )
        is None
    )


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        (order_data(total="90.00"), None),
        (order_data(currency="PKR"), None),
        (order_data(status="pending"), None),
        (order_data(status="cancelled"), None),
        (order_data(status="refunded"), None),
        (order_data(order_id="OTHER-ORDER"), None),
        (order_data(), "TXN-B"),
    ],
)
def test_order_eligibility(
    order: dict[str, object],
    expected: str | None,
) -> None:
    candidate = detect_duplicate_payment_candidate(
        tool_results=build_results(
            payments=matching_payments(),
            orders=[order],
        )
    )

    assert (candidate.duplicate_transaction_id if candidate is not None else None) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", "99.00"),
        ("currency", "PKR"),
        ("provider", "other_gateway"),
        ("payment_instrument_fingerprint", "different-token"),
        ("status", "failed"),
        ("transaction_type", "refund"),
        ("external_transaction_id", "TXN-A"),
        ("processed_at", "2026-10-08T11:00:00Z"),
    ],
)
def test_mismatched_or_ambiguous_charges_rejected(
    field: str,
    value: object,
) -> None:
    payments = matching_payments()
    payments[1][field] = value

    assert (
        detect_duplicate_payment_candidate(
            tool_results=build_results(
                payments=payments,
                orders=[order_data()],
            )
        )
        is None
    )


def test_three_charges_are_ambiguous() -> None:
    payments = matching_payments()
    payments.append(
        payment_data(
            "TXN-C",
            "2026-10-08T10:02:00Z",
        )
    )

    assert (
        detect_duplicate_payment_candidate(
            tool_results=build_results(
                payments=payments,
                orders=[order_data()],
            )
        )
        is None
    )


def test_two_different_orders_do_not_match() -> None:
    assert (
        detect_duplicate_payment_candidate(
            tool_results=build_results(
                payments=matching_payments(),
                orders=[order_data(order_id="ORD-OTHER")],
            )
        )
        is None
    )


def test_payment_provider_can_be_synthetic() -> None:
    candidate = detect_duplicate_payment_candidate(
        tool_results=build_results(
            payments=matching_payments(),
            orders=[order_data()],
        )
    )

    assert candidate is not None
    assert candidate.provider == "demo_gateway"


@pytest.mark.parametrize(
    "provider",
    [
        "",
        " ",
        "unknown",
        "UNKNOWN",
        "undefined",
        "none",
        "null",
        "n/a",
        "na",
        "unavailable",
        "unspecified",
    ],
)
def test_rejects_placeholder_payment_provider(
    provider: str,
) -> None:
    payments = matching_payments()

    payments[0]["provider"] = provider
    payments[1]["provider"] = provider

    candidate = detect_duplicate_payment_candidate(
        tool_results=build_results(
            payments=payments,
            orders=[order_data()],
        )
    )

    assert candidate is None


@pytest.mark.parametrize(
    "provider",
    [
        "stripe",
        "paypal",
        "demo_gateway",
        "adyen",
    ],
)
def test_accepts_matching_identified_provider(
    provider: str,
) -> None:
    payments = matching_payments()

    payments[0]["provider"] = provider
    payments[1]["provider"] = provider

    candidate = detect_duplicate_payment_candidate(
        tool_results=build_results(
            payments=payments,
            orders=[order_data()],
        )
    )

    assert candidate is not None
    assert candidate.provider == provider
