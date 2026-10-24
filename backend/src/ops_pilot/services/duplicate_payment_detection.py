import json
from datetime import datetime

from pydantic import ValidationError

from ops_pilot.models.payment_transaction import (
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.schemas.duplicate_payments import (
    DuplicatePaymentCandidate,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    PaymentTransactionData,
    ToolExecutionResult,
)

MAX_DUPLICATE_PAYMENT_WINDOW_SECONDS = 300


def detect_duplicate_payment_candidate(
    *,
    tool_results: list[ToolExecutionResult],
) -> DuplicatePaymentCandidate | None:
    candidates: list[DuplicatePaymentCandidate] = []

    for result in tool_results:
        if not result.success or result.tool_name != OperationalToolName.LIST_ORDER_PAYMENTS:
            continue

        order_id = result.arguments.get(
            "order_id",
        )

        if not isinstance(
            order_id,
            str,
        ):
            continue

        try:
            raw_payments = json.loads(
                result.content,
            )
        except json.JSONDecodeError:
            continue

        if not isinstance(
            raw_payments,
            list,
        ):
            continue

        valid_payments: list[
            tuple[
                PaymentTransactionData,
                datetime,
            ]
        ] = []

        for raw_payment in raw_payments:
            try:
                payment = PaymentTransactionData.model_validate(
                    raw_payment,
                )
            except ValidationError:
                continue

            if payment.transaction_type != PaymentTransactionType.CHARGE:
                continue

            if payment.status != PaymentTransactionStatus.SUCCEEDED:
                continue

            processed_at = payment.processed_at

            if processed_at is None:
                continue

            valid_payments.append(
                (
                    payment,
                    processed_at,
                )
            )

        if len(valid_payments) != 2:
            continue

        valid_payments.sort(
            key=lambda item: item[1],
        )

        original, original_processed_at = valid_payments[0]

        duplicate, duplicate_processed_at = valid_payments[1]

        # Identical transaction IDs are not evidence of two charges.
        if original.external_transaction_id == duplicate.external_transaction_id:
            continue

        if original.amount != duplicate.amount:
            continue

        if original.currency.upper() != duplicate.currency.upper():
            continue

        if original.provider != duplicate.provider:
            continue

        elapsed_seconds = (duplicate_processed_at - original_processed_at).total_seconds()

        if elapsed_seconds <= 0:
            continue

        if elapsed_seconds > MAX_DUPLICATE_PAYMENT_WINDOW_SECONDS:
            continue

        candidates.append(
            DuplicatePaymentCandidate(
                order_id=order_id,
                original_transaction_id=(original.external_transaction_id),
                duplicate_transaction_id=(duplicate.external_transaction_id),
                amount=duplicate.amount,
                currency=duplicate.currency,
                provider=duplicate.provider,
                original_processed_at=(original_processed_at),
                duplicate_processed_at=(duplicate_processed_at),
                seconds_apart=int(elapsed_seconds),
            )
        )

    if len(candidates) != 1:
        return None

    return candidates[0]
