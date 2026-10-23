import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    ApprovalExecutionError,
)
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
from ops_pilot.schemas.action_execution import (
    RefundExecutionResult,
)


async def verify_refund_execution(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    execution: RefundExecutionResult,
) -> None:
    approval_result = await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_request_id,
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.incident_id == incident_id,
        )
    )

    approval = approval_result.scalar_one_or_none()

    if approval is None:
        raise ApprovalExecutionError(
            "Approval missing during verification",
        )

    if approval.status != ApprovalStatus.EXECUTED:
        raise ApprovalExecutionError(
            "Approval was not marked executed",
        )

    source_result = await session.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.organization_id == organization_id,
            PaymentTransaction.external_transaction_id == execution.source_transaction_id,
        )
    )

    source = source_result.scalar_one_or_none()

    if source is None:
        raise ApprovalExecutionError(
            "Source transaction missing during verification",
        )

    if source.transaction_type != PaymentTransactionType.CHARGE:
        raise ApprovalExecutionError(
            "Verified source is not a charge",
        )

    if source.status != PaymentTransactionStatus.REFUNDED:
        raise ApprovalExecutionError(
            "Source charge was not marked refunded",
        )

    refund_result = await session.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.organization_id == organization_id,
            PaymentTransaction.external_transaction_id == execution.refund_transaction_id,
            PaymentTransaction.source_transaction_id == source.id,
            PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
        )
    )

    refund = refund_result.scalar_one_or_none()

    if refund is None:
        raise ApprovalExecutionError(
            "Refund transaction missing during verification",
        )

    if refund.status != PaymentTransactionStatus.SUCCEEDED:
        raise ApprovalExecutionError(
            "Refund transaction did not succeed",
        )

    if refund.amount != source.amount:
        raise ApprovalExecutionError(
            "Verified refund amount does not match source charge",
        )

    if refund.currency != source.currency:
        raise ApprovalExecutionError(
            "Verified refund currency does not match source charge",
        )

    incident_result = await session.execute(
        select(Incident).where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
    )

    incident = incident_result.scalar_one_or_none()

    if incident is None:
        raise ApprovalExecutionError(
            "Incident missing during verification",
        )

    incident.status = IncidentStatus.RESOLVED

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
