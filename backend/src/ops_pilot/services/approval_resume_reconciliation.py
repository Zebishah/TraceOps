"""Reconcile uncertain approval jobs without replaying payments."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select, update

from ops_pilot.db.session import async_session_factory
from ops_pilot.models.approval import ApprovalRequest, ApprovalStatus
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
)
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.services.approval_resume_processor import (
    verify_terminal_checkpoint,
)
from ops_pilot.services.approval_resume_recovery import MAX_ATTEMPTS
from ops_pilot.workflows.incident.checkpointing import (
    open_incident_checkpointer,
)
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationResult:
    inspected: int
    completed: int
    unresolved: int


async def verify_quarantined_job(
    *,
    job_id: uuid.UUID,
) -> bool:
    """Return True only for a verified terminal workflow."""

    async with async_session_factory() as session:
        result = await session.execute(
            select(ApprovalRequest)
            .join(
                ApprovalResumeJob,
                ApprovalResumeJob.approval_request_id == ApprovalRequest.id,
            )
            .where(
                ApprovalResumeJob.id == job_id,
                ApprovalResumeJob.organization_id == ApprovalRequest.organization_id,
                ApprovalResumeJob.incident_id == ApprovalRequest.incident_id,
            )
        )
        approval = result.scalar_one_or_none()

        if approval is None:
            return False

        status = approval.status
        thread_id = approval.workflow_thread_id
        organization_id = approval.organization_id
        incident_id = approval.incident_id
        approval_request_id = approval.id
        source_external_id = approval.action_payload.get("external_transaction_id")

        await session.rollback()

    if status not in {
        ApprovalStatus.EXECUTED,
        ApprovalStatus.REJECTED,
    }:
        return False

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    async with open_incident_checkpointer() as checkpointer:
        graph = build_incident_investigation_graph(
            checkpointer=checkpointer,
        )

        try:
            await verify_terminal_checkpoint(
                graph=graph,
                config=config,
                approval_status=status,
            )
        except (RuntimeError, ValueError):
            return False

    # A rejected approval has no refund to verify.
    if status == ApprovalStatus.REJECTED:
        return True

    # An executed approval must also have a consistent
    # persisted refund and resolved incident.
    if status == ApprovalStatus.REJECTED:
        return True

    if not isinstance(source_external_id, str):
        return False

    return await verify_persisted_refund(
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_request_id,
        source_external_id=source_external_id,
    )


async def verify_persisted_refund(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    source_external_id: str,
) -> bool:
    if not isinstance(source_external_id, str):
        return False

    async with async_session_factory() as session:
        source = await session.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.organization_id == organization_id,
                PaymentTransaction.external_transaction_id == source_external_id,
                PaymentTransaction.transaction_type == PaymentTransactionType.CHARGE,
            )
        )

        if source is None:
            return False

        refund = await session.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.organization_id == organization_id,
                PaymentTransaction.source_transaction_id == source.id,
                PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                PaymentTransaction.status == PaymentTransactionStatus.SUCCEEDED,
            )
        )

        incident = await session.scalar(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.organization_id == organization_id,
            )
        )

        valid = (
            refund is not None
            and incident is not None
            and incident.status == IncidentStatus.RESOLVED
            and source.status == PaymentTransactionStatus.REFUNDED
            and refund.amount == source.amount
            and refund.currency == source.currency
            and refund.order_id == source.order_id
        )

        await session.rollback()
        return valid


async def reconcile_quarantined_jobs(
    *,
    limit: int = 20,
) -> ReconciliationResult:
    """Mark verified jobs complete; leave uncertain jobs untouched."""

    if limit < 1:
        raise ValueError("limit must be positive")

    async with async_session_factory() as session:
        result = await session.execute(
            select(ApprovalResumeJob.id)
            .where(
                ApprovalResumeJob.status == ApprovalResumeJobStatus.FAILED.value,
                ApprovalResumeJob.attempts >= MAX_ATTEMPTS,
                ApprovalResumeJob.last_error.is_not(None),
            )
            .order_by(ApprovalResumeJob.updated_at)
            .limit(limit)
        )
        ids = list(result.scalars().all())
        await session.rollback()

    completed = 0

    for job_id in ids:
        try:
            verified = await verify_quarantined_job(
                job_id=job_id,
            )

            if not verified:
                continue

            async with async_session_factory() as session:
                result = await session.execute(
                    update(ApprovalResumeJob)
                    .where(
                        ApprovalResumeJob.id == job_id,
                        ApprovalResumeJob.status == ApprovalResumeJobStatus.FAILED.value,
                        ApprovalResumeJob.attempts >= MAX_ATTEMPTS,
                        ApprovalResumeJob.last_error.is_not(None),
                    )
                    .values(
                        status=ApprovalResumeJobStatus.COMPLETED.value,
                        completed_at=datetime.now(UTC),
                        last_error=None,
                        lease_token=None,
                        lease_expires_at=None,
                    )
                    .returning(ApprovalResumeJob.id)
                )
                updated_id = result.scalar_one_or_none()
                await session.commit()

                if updated_id is not None:
                    completed += 1

        except Exception:
            logger.exception(
                "approval_reconciliation_error",
                extra={"job_id": str(job_id)},
            )

    return ReconciliationResult(
        inspected=len(ids),
        completed=completed,
        unresolved=len(ids) - completed,
    )
