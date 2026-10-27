import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import ApprovalExecutionError
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.models.order import OperationalOrder
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionType,
)
from ops_pilot.schemas.action_execution import RefundExecutionResult
from ops_pilot.services.refund_execution import validate_existing_refund


async def verify_refund_execution(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    execution: RefundExecutionResult,
) -> None:
    # Consistent lock ordering:
    # INCIDENT -> APPROVAL -> SOURCE -> REFUND.
    incident_result = await session.execute(
        select(Incident)
        .where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    incident = incident_result.scalar_one_or_none()

    if incident is None:
        raise ApprovalExecutionError("Incident missing during verification")

    approval_result = await session.execute(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_request_id,
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.incident_id == incident_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    approval = approval_result.scalar_one_or_none()

    if approval is None:
        raise ApprovalExecutionError("Approval missing during verification")

    if (
        approval.status != ApprovalStatus.EXECUTED
        or approval.action_type != ApprovalActionType.REFUND_TRANSACTION
        or approval.decided_by_user_id is None
        or approval.decided_at is None
        or approval.executed_at is None
    ):
        raise ApprovalExecutionError("Approval is not a valid executed human decision")

    source_result = await session.execute(
        select(PaymentTransaction)
        .join(
            OperationalOrder,
            PaymentTransaction.order_id == OperationalOrder.id,
        )
        .where(
            PaymentTransaction.organization_id == organization_id,
            OperationalOrder.organization_id == organization_id,
            PaymentTransaction.external_transaction_id == execution.source_transaction_id,
            PaymentTransaction.transaction_type == PaymentTransactionType.CHARGE,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    source = source_result.scalar_one_or_none()

    if source is None:
        raise ApprovalExecutionError("Source charge missing during verification")

    refund_result = await session.execute(
        select(PaymentTransaction)
        .where(
            PaymentTransaction.organization_id == organization_id,
            PaymentTransaction.external_transaction_id == execution.refund_transaction_id,
            PaymentTransaction.source_transaction_id == source.id,
            PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    refund = refund_result.scalar_one_or_none()

    if refund is None:
        raise ApprovalExecutionError("Refund ledger record missing during verification")

    # One canonical set of financial consistency rules
    # is shared with refund execution and recovery.
    validate_existing_refund(
        approval=approval,
        source=source,
        refund=refund,
    )

    # The graph's execution result must describe the exact
    # persisted financial records being verified.
    if (
        execution.source_transaction_id != source.external_transaction_id
        or execution.refund_transaction_id != refund.external_transaction_id
        or execution.amount != refund.amount
        or execution.currency != refund.currency
    ):
        raise ApprovalExecutionError("Execution result does not match persisted refund")

    if incident.status not in {
        IncidentStatus.AWAITING_APPROVAL,
        IncidentStatus.RESOLVED,
    }:
        raise ApprovalExecutionError("Incident is not eligible for refund verification")

    # Idempotent replay: never overwrite prior resolution
    # attribution or reason.
    if incident.status == IncidentStatus.RESOLVED:
        if (
            incident.resolved_by_user_id != approval.decided_by_user_id
            or incident.resolved_at is None
            or incident.resolution_reason is None
            or "internal refund ledger" not in incident.resolution_reason.lower()
        ):
            raise ApprovalExecutionError("Existing incident resolution is inconsistent")

        await session.rollback()
        return

    incident.status = IncidentStatus.RESOLVED
    incident.resolved_by_user_id = approval.decided_by_user_id
    incident.resolved_at = datetime.now(UTC)
    incident.resolution_reason = (
        "Approved internal refund ledger entry recorded "
        f"for charge {source.external_transaction_id}. "
        f"Ledger refund reference: {refund.external_transaction_id}. "
        "No external payment provider refund was initiated or confirmed."
    )

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
