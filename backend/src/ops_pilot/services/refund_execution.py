import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    ApprovalExecutionError,
)
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.order import OperationalOrder
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.schemas.action_execution import (
    RefundExecutionResult,
)


async def execute_approved_refund(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> RefundExecutionResult:
    approval_result = await session.execute(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_request_id,
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.incident_id == incident_id,
        )
        .with_for_update()
    )

    approval = approval_result.scalar_one_or_none()

    if approval is None:
        raise ApprovalExecutionError(
            "Approval request not found",
        )

    if approval.action_type != ApprovalActionType.REFUND_TRANSACTION:
        raise ApprovalExecutionError(
            "Unsupported approval action",
        )

    if approval.status == ApprovalStatus.EXECUTED:
        payload = approval.action_payload

        source_external_id = payload.get("external_transaction_id")

        if not isinstance(
            source_external_id,
            str,
        ):
            raise ApprovalExecutionError(
                "Executed approval has invalid payload",
            )

        existing_result = await session.execute(
            select(PaymentTransaction)
            .join(
                OperationalOrder,
                PaymentTransaction.order_id == OperationalOrder.id,
            )
            .where(
                PaymentTransaction.organization_id == organization_id,
                OperationalOrder.organization_id == organization_id,
                OperationalOrder.customer_id == customer_id,
                PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                PaymentTransaction.external_transaction_id == f"refund-{approval.id}",
            )
        )

        existing_refund = existing_result.scalar_one_or_none()

        if existing_refund is None:
            raise ApprovalExecutionError(
                "Executed approval is missing its refund transaction",
            )

        return RefundExecutionResult(
            source_transaction_id=source_external_id,
            refund_transaction_id=(existing_refund.external_transaction_id),
            amount=existing_refund.amount,
            currency=existing_refund.currency,
            already_executed=True,
        )

    if approval.status != ApprovalStatus.APPROVED:
        raise ApprovalExecutionError(
            "Refund execution requires an approved request",
        )
    if approval.decided_by_user_id is None or approval.decided_at is None:
        raise ApprovalExecutionError("Refund execution requires a recorded human approval")
    payload = approval.action_payload

    external_transaction_id = payload.get("external_transaction_id")
    expected_amount = payload.get("amount")
    expected_currency = payload.get("currency")

    if (
        not isinstance(
            external_transaction_id,
            str,
        )
        or not isinstance(
            expected_amount,
            str,
        )
        or not isinstance(
            expected_currency,
            str,
        )
    ):
        raise ApprovalExecutionError(
            "Approval action payload is invalid",
        )

    try:
        proposed_amount = Decimal(expected_amount)
    except Exception as exc:
        raise ApprovalExecutionError(
            "Approval amount is invalid",
        ) from exc

    source_result = await session.execute(
        select(PaymentTransaction)
        .join(
            OperationalOrder,
            PaymentTransaction.order_id == OperationalOrder.id,
        )
        .where(
            PaymentTransaction.organization_id == organization_id,
            OperationalOrder.organization_id == organization_id,
            OperationalOrder.customer_id == customer_id,
            PaymentTransaction.external_transaction_id == external_transaction_id,
        )
        .with_for_update()
    )

    source_transaction = source_result.scalar_one_or_none()

    if source_transaction is None:
        raise ApprovalExecutionError(
            "Source transaction not found",
        )

    if source_transaction.transaction_type != PaymentTransactionType.CHARGE:
        raise ApprovalExecutionError(
            "Only charge transactions can be refunded",
        )

    if source_transaction.status == PaymentTransactionStatus.REFUNDED:
        existing_result = await session.execute(
            select(PaymentTransaction)
            .join(
                OperationalOrder,
                PaymentTransaction.order_id == OperationalOrder.id,
            )
            .where(
                PaymentTransaction.organization_id == organization_id,
                OperationalOrder.organization_id == organization_id,
                OperationalOrder.customer_id == customer_id,
                PaymentTransaction.source_transaction_id == source_transaction.id,
                PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
            )
        )

        existing_refund = existing_result.scalar_one_or_none()

        if existing_refund is None:
            raise ApprovalExecutionError(
                "Source charge is marked refunded but no refund record exists",
            )

        approval.status = ApprovalStatus.EXECUTED

        if approval.executed_at is None:
            approval.executed_at = datetime.now(UTC)

        await session.commit()

        return RefundExecutionResult(
            source_transaction_id=(source_transaction.external_transaction_id),
            refund_transaction_id=(existing_refund.external_transaction_id),
            amount=existing_refund.amount,
            currency=existing_refund.currency,
            already_executed=True,
        )

    if source_transaction.status != PaymentTransactionStatus.SUCCEEDED:
        raise ApprovalExecutionError(
            "Only successful charges can be refunded",
        )

    if source_transaction.amount != proposed_amount:
        raise ApprovalExecutionError(
            "Approved refund amount does not match the source transaction",
        )

    if source_transaction.currency.upper() != expected_currency.upper():
        raise ApprovalExecutionError(
            "Approved refund currency does not match the source transaction",
        )

    existing_refund_result = await session.execute(
        select(PaymentTransaction)
        .join(
            OperationalOrder,
            PaymentTransaction.order_id == OperationalOrder.id,
        )
        .where(
            PaymentTransaction.organization_id == organization_id,
            OperationalOrder.organization_id == organization_id,
            OperationalOrder.customer_id == customer_id,
            PaymentTransaction.source_transaction_id == source_transaction.id,
            PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
        )
    )
    existing_refund = existing_refund_result.scalar_one_or_none()

    if existing_refund is not None:
        source_transaction.status = PaymentTransactionStatus.REFUNDED

        approval.status = ApprovalStatus.EXECUTED
        approval.executed_at = approval.executed_at or datetime.now(UTC)

        await session.commit()

        return RefundExecutionResult(
            source_transaction_id=(source_transaction.external_transaction_id),
            refund_transaction_id=(existing_refund.external_transaction_id),
            amount=existing_refund.amount,
            currency=existing_refund.currency,
            already_executed=True,
        )

    refund = PaymentTransaction(
        organization_id=organization_id,
        order_id=source_transaction.order_id,
        source_transaction_id=(source_transaction.id),
        external_transaction_id=(f"refund-{approval.id}"),
        provider=source_transaction.provider,
        transaction_type=(PaymentTransactionType.REFUND),
        amount=source_transaction.amount,
        currency=source_transaction.currency,
        status=(PaymentTransactionStatus.SUCCEEDED),
        processed_at=datetime.now(UTC),
    )

    source_transaction.status = PaymentTransactionStatus.REFUNDED

    approval.status = ApprovalStatus.EXECUTED
    approval.executed_at = datetime.now(UTC)

    session.add(refund)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(refund)

    return RefundExecutionResult(
        source_transaction_id=(source_transaction.external_transaction_id),
        refund_transaction_id=(refund.external_transaction_id),
        amount=refund.amount,
        currency=refund.currency,
        already_executed=False,
    )
