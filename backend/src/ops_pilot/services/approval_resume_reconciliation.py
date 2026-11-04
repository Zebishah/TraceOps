"""Reconcile uncertain approval jobs without replaying payments."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    PaymentTransactionType,
)
from ops_pilot.services.approval_resume_processor import (
    verify_resume_outcome,
)
from ops_pilot.services.approval_resume_recovery import (
    MAX_ATTEMPTS,
    ClaimedResumeJob,
)
from ops_pilot.workflows.incident.checkpointing import (
    open_incident_checkpointer,
)
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)

RECONCILIATION_RECHECK_SECONDS = 600
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
    """Verify a quarantined job without replaying the workflow.

    Completion requires:
    - Correct tenant, incident, and approval
    - A terminal LangGraph checkpoint
    - A matching persisted refund for executed approvals
    """

    async with async_session_factory() as session:
        result = await session.execute(
            select(ApprovalRequest, ApprovalResumeJob)
            .join(
                ApprovalResumeJob,
                ApprovalResumeJob.approval_request_id == ApprovalRequest.id,
            )
            .where(
                ApprovalResumeJob.id == job_id,
                ApprovalResumeJob.organization_id == ApprovalRequest.organization_id,
                ApprovalResumeJob.incident_id == ApprovalRequest.incident_id,
                ApprovalResumeJob.approval_request_id == ApprovalRequest.id,
            )
        )

        record = result.one_or_none()

        if record is None:
            await session.rollback()
            return False

        approval, persisted_job = record

        status = approval.status
        thread_id = approval.workflow_thread_id

        source_value = approval.action_payload.get("external_transaction_id")

        source_external_id = source_value if isinstance(source_value, str) else None

        # The reconciliation path only reads these
        # identifiers. It does not claim or renew a lease.
        checkpoint_identity = ClaimedResumeJob(
            id=persisted_job.id,
            organization_id=persisted_job.organization_id,
            incident_id=persisted_job.incident_id,
            approval_request_id=persisted_job.approval_request_id,
            lease_token=(persisted_job.lease_token or uuid.UUID(int=0)),
            attempts=persisted_job.attempts,
        )

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
            await verify_resume_outcome(
                graph=graph,
                config=config,
                job=checkpoint_identity,
                approval_status=status,
                source_external_id=source_external_id,
            )

        except (RuntimeError, ValueError):
            logger.warning(
                "approval_reconciliation_not_verified",
                extra={"job_id": str(job_id)},
            )
            return False

    return True


async def verify_persisted_refund(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    source_external_id: str,
) -> bool:
    """Verify the exact executed approval, charge, refund, and incident."""

    from ops_pilot.core.exceptions import ApprovalExecutionError
    from ops_pilot.models.order import OperationalOrder
    from ops_pilot.services.refund_execution import validate_existing_refund

    if not source_external_id:
        return False

    async with async_session_factory() as session:
        try:
            approval = await session.scalar(
                select(ApprovalRequest).where(
                    ApprovalRequest.id == approval_request_id,
                    ApprovalRequest.organization_id == organization_id,
                    ApprovalRequest.incident_id == incident_id,
                    ApprovalRequest.status == ApprovalStatus.EXECUTED,
                )
            )

            incident = await session.scalar(
                select(Incident).where(
                    Incident.id == incident_id,
                    Incident.organization_id == organization_id,
                    Incident.status == IncidentStatus.RESOLVED,
                )
            )

            if approval is None or incident is None:
                return False

            source = await session.scalar(
                select(PaymentTransaction)
                .join(
                    OperationalOrder,
                    PaymentTransaction.order_id == OperationalOrder.id,
                )
                .where(
                    PaymentTransaction.organization_id == organization_id,
                    OperationalOrder.organization_id == organization_id,
                    OperationalOrder.customer_id == incident.subject_customer_id,
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
                )
            )

            if refund is None:
                return False

            validate_existing_refund(
                approval=approval,
                source=source,
                refund=refund,
            )

            return True

        except ApprovalExecutionError:
            return False
        finally:
            await session.rollback()


async def reconcile_quarantined_jobs(
    *,
    limit: int = 20,
) -> ReconciliationResult:
    """Inspect quarantined jobs without unsafe automatic completion.

    Until checkpoint writes and job completion share a proven
    synchronization mechanism, a verified result is evidence
    for operator review, not permission to complete the job.

    Quarantined jobs stay FAILED and cannot be claimed for
    automatic financial execution.
    """
    if limit < 1:
        raise ValueError("limit must be positive")

    now = datetime.now(UTC)

    async with async_session_factory() as session:
        result = await session.execute(
            select(ApprovalResumeJob.id)
            .where(
                ApprovalResumeJob.status == ApprovalResumeJobStatus.FAILED.value,
                ApprovalResumeJob.attempts >= MAX_ATTEMPTS,
                ApprovalResumeJob.last_error.is_not(None),
                ApprovalResumeJob.next_attempt_at <= now,
            )
            .order_by(
                ApprovalResumeJob.next_attempt_at,
                ApprovalResumeJob.updated_at,
                ApprovalResumeJob.id,
            )
            .limit(limit)
        )

        ids = list(result.scalars().all())
        await session.rollback()

    for job_id in ids:
        try:
            verified = await verify_quarantined_job(
                job_id=job_id,
            )

            if verified:
                logger.warning(
                    "approval_reconciliation_verified_requires_review",
                    extra={"job_id": str(job_id)},
                )
            else:
                logger.warning(
                    "approval_reconciliation_unresolved",
                    extra={"job_id": str(job_id)},
                )

        except Exception:
            logger.exception(
                "approval_reconciliation_error",
                extra={"job_id": str(job_id)},
            )

        # Reschedule verification regardless of the result.
        # This update never clears quarantine or changes
        # approval, payment, or workflow state.
        try:
            async with async_session_factory() as session:
                await session.execute(
                    update(ApprovalResumeJob)
                    .where(
                        ApprovalResumeJob.id == job_id,
                        ApprovalResumeJob.status == ApprovalResumeJobStatus.FAILED.value,
                        ApprovalResumeJob.attempts >= MAX_ATTEMPTS,
                        ApprovalResumeJob.last_error.is_not(None),
                    )
                    .values(
                        next_attempt_at=(
                            datetime.now(UTC) + timedelta(seconds=RECONCILIATION_RECHECK_SECONDS)
                        ),
                    )
                )

                await session.commit()

        except Exception:
            logger.exception(
                "approval_reconciliation_reschedule_failed",
                extra={"job_id": str(job_id)},
            )

    return ReconciliationResult(
        inspected=len(ids),
        completed=0,
        unresolved=len(ids),
    )
