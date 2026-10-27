import json
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from ops_pilot.models.order import OrderStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.schemas.duplicate_payments import DuplicatePaymentCandidate
from ops_pilot.tools.schemas import (
    OperationalOrderData,
    OperationalToolName,
    PaymentTransactionData,
    ToolExecutionResult,
)

MAX_DUPLICATE_PAYMENT_WINDOW_SECONDS = 300


def _eligible_orders(
    tool_results: list[ToolExecutionResult],
) -> dict[str, OperationalOrderData]:
    orders: dict[str, OperationalOrderData] = {}
    ambiguous: set[str] = set()

    for result in tool_results:
        if not result.success or result.tool_name != OperationalToolName.LIST_CUSTOMER_ORDERS:
            continue

        try:
            payload = json.loads(result.content)
        except (ValueError, TypeError):
            continue

        if not isinstance(payload, list):
            continue

        for item in payload:
            try:
                order = OperationalOrderData.model_validate(item)
            except ValidationError:
                continue

            identifier = order.external_order_id

            if not identifier or not identifier.strip():
                continue

            if identifier in orders:
                ambiguous.add(identifier)
                continue

            orders[identifier] = order

    for identifier in ambiguous:
        orders.pop(identifier, None)

    return orders


def detect_duplicate_payment_candidate(
    *,
    tool_results: list[ToolExecutionResult],
) -> DuplicatePaymentCandidate | None:
    orders = _eligible_orders(tool_results)

    candidates: list[DuplicatePaymentCandidate] = []
    seen_orders: set[str] = set()

    for result in tool_results:
        if not result.success or result.tool_name != OperationalToolName.LIST_ORDER_PAYMENTS:
            continue

        order_id = result.arguments.get("order_id")

        if not isinstance(order_id, str) or not order_id.strip():
            continue

        # Do not trust payment data unless the order was
        # independently returned by the operational order tool.
        order = orders.get(order_id)

        if order is None or order_id in seen_orders:
            continue

        seen_orders.add(order_id)

        if order.status != OrderStatus.PAID:
            continue

        if not order.total_amount.is_finite() or order.total_amount <= Decimal("0"):
            continue

        try:
            payload = json.loads(result.content)
        except (ValueError, TypeError):
            continue

        if not isinstance(payload, list):
            continue

        # Only accept exactly two records. Any extra payment,
        # including refunds, makes this demo scenario
        # ambiguous and requires manual investigation.
        if len(payload) != 2:
            continue

        valid: list[tuple[PaymentTransactionData, datetime]] = []

        for item in payload:
            try:
                payment = PaymentTransactionData.model_validate(item)
            except ValidationError:
                break

            if (
                payment.transaction_type != PaymentTransactionType.CHARGE
                or payment.status != PaymentTransactionStatus.SUCCEEDED
                or payment.processed_at is None
                or not payment.amount.is_finite()
                or payment.amount <= 0
            ):
                break

            valid.append((payment, payment.processed_at))

        if len(valid) != 2:
            continue

        valid.sort(key=lambda item: item[1])

        original, original_time = valid[0]
        duplicate, duplicate_time = valid[1]

        if original.external_transaction_id == duplicate.external_transaction_id:
            continue

        # Demo policy: two complete charges for the
        # same order, not partial or installment payments.
        if (
            original.amount != duplicate.amount
            or original.amount != order.total_amount
            or original.currency != duplicate.currency
            or original.currency != order.currency
        ):
            continue

        # Accept matching real or synthetic provider identifiers,
        # but reject placeholders that cannot establish identity.
        invalid_providers = {
            "",
            "unknown",
            "undefined",
            "none",
            "null",
            "n/a",
            "na",
            "unavailable",
            "unspecified",
        }

        original_provider = original.provider.strip().lower()
        duplicate_provider = duplicate.provider.strip().lower()

        if (
            original_provider in invalid_providers
            or duplicate_provider in invalid_providers
            or original_provider != duplicate_provider
        ):
            continue

        first_fingerprint = original.payment_instrument_fingerprint
        second_fingerprint = duplicate.payment_instrument_fingerprint

        if (
            not first_fingerprint
            or not second_fingerprint
            or not first_fingerprint.strip()
            or first_fingerprint != second_fingerprint
        ):
            continue

        elapsed = (duplicate_time - original_time).total_seconds()

        if elapsed <= 0 or elapsed > MAX_DUPLICATE_PAYMENT_WINDOW_SECONDS:
            continue

        candidates.append(
            DuplicatePaymentCandidate(
                order_id=order_id,
                original_transaction_id=(original.external_transaction_id),
                duplicate_transaction_id=(duplicate.external_transaction_id),
                amount=duplicate.amount,
                currency=duplicate.currency,
                provider=duplicate_provider,
                original_processed_at=original_time,
                duplicate_processed_at=duplicate_time,
                seconds_apart=int(elapsed),
            )
        )

    if len(candidates) != 1:
        return None

    return candidates[0]
