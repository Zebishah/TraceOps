import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    ApprovalDecisionConflictError,
    ApprovalNotFoundError,
)
from ops_pilot.models.approval import (
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
)
from ops_pilot.models.incident import (
    Incident,
    IncidentStatus,
)
from ops_pilot.schemas.approvals import (
    ApprovalDecisionRequest,
)
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
)
from ops_pilot.services.incident_resolution import (
    IncidentResolutionConflict,
)


async def create_or_get_pending_approval(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    workflow_thread_id: str,
    proposal: IncidentActionProposal,
) -> ApprovalRequest:
    if (
        not proposal.requires_approval
        or proposal.action_type is None
        or proposal.external_transaction_id is None
        or proposal.amount is None
        or proposal.currency is None
        or not proposal.reason
    ):
        raise ValueError("Approval requires a complete action proposal")

    try:
        # Lock incident first to serialize approval creation
        # with other workflows and manual incident updates.
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
            raise RuntimeError("Incident not found while creating approval")

        if incident.status == IncidentStatus.RESOLVED:
            raise IncidentResolutionConflict("Cannot create approval for a resolved incident")

        if incident.status not in {
            IncidentStatus.INVESTIGATING,
            IncidentStatus.AWAITING_APPROVAL,
        }:
            raise IncidentResolutionConflict("Incident is not eligible for approval creation")

        expected_payload = {
            "external_transaction_id": (proposal.external_transaction_id),
            "amount": str(proposal.amount),
            "currency": proposal.currency,
        }

        # Search for every ACTIVE approval, regardless
        # of which workflow originally created it.
        active_result = await session.execute(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.incident_id == incident_id,
                ApprovalRequest.status.in_(
                    [
                        ApprovalStatus.PENDING,
                        ApprovalStatus.APPROVED,
                    ]
                ),
            )
            .with_for_update()
        )

        active = active_result.scalars().all()

        if len(active) > 1:
            raise ApprovalDecisionConflictError("Incident has conflicting active approvals")

        if active:
            existing = active[0]

            # Only an identical retry from the same
            # workflow can reuse the pending approval.
            if (
                existing.status != ApprovalStatus.PENDING
                or existing.workflow_thread_id != workflow_thread_id
                or existing.action_type != proposal.action_type
                or existing.action_payload != expected_payload
            ):
                raise ApprovalDecisionConflictError(
                    "Another active approval already exists for this incident"
                )

            await session.rollback()
            return existing

        approval = ApprovalRequest(
            organization_id=organization_id,
            incident_id=incident_id,
            workflow_thread_id=workflow_thread_id,
            action_type=proposal.action_type,
            action_payload=expected_payload,
            reason=proposal.reason,
            status=ApprovalStatus.PENDING,
        )

        incident.status = IncidentStatus.AWAITING_APPROVAL
        session.add(approval)

        await session.commit()
        await session.refresh(approval)

        return approval

    except Exception:
        await session.rollback()
        raise


async def get_approval_request(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
) -> ApprovalRequest:
    result = await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_request_id,
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.incident_id == incident_id,
        )
    )

    approval = result.scalar_one_or_none()

    if approval is None:
        raise ApprovalNotFoundError

    return approval


async def record_approval_decision(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    decided_by_user_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
) -> ApprovalRequest:
    # Lock order: INCIDENT -> APPROVAL.
    # Matches manual incident closure and approval creation.
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
        await session.rollback()
        raise ApprovalNotFoundError

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
        await session.rollback()
        raise ApprovalNotFoundError

    desired_status = ApprovalStatus.APPROVED if payload.approved else ApprovalStatus.REJECTED

    # Idempotent retries should not modify database state.

    # Identical retries are idempotent.
    if approval.status == desired_status or (
        approval.status == ApprovalStatus.EXECUTED and payload.approved
    ):
        try:
            if approval.status in {
                ApprovalStatus.APPROVED,
                ApprovalStatus.REJECTED,
            }:
                await ensure_approval_resume_job(
                    session=session,
                    approval=approval,
                )

            await session.commit()

        except Exception:
            await session.rollback()
            raise

        await session.refresh(approval)
        return approval

    # A final decision cannot be reversed.
    if approval.status != ApprovalStatus.PENDING:
        await session.rollback()
        raise ApprovalDecisionConflictError

    # Do not decide approvals for closed incidents.
    if incident.status == IncidentStatus.RESOLVED:
        await session.rollback()
        raise IncidentResolutionConflict("Cannot decide approval for a resolved incident")

    if incident.status != IncidentStatus.AWAITING_APPROVAL:
        await session.rollback()
        raise IncidentResolutionConflict("Incident is not awaiting approval")

    # Record the actual human decision.
    approval.status = desired_status
    approval.decided_by_user_id = decided_by_user_id
    approval.decision_comment = payload.comment
    approval.decided_at = datetime.now(UTC)

    if not payload.approved:
        incident.status = IncidentStatus.INVESTIGATING

    # Decision and durable resume job commit together.
    try:
        await ensure_approval_resume_job(
            session=session,
            approval=approval,
        )

        await session.commit()

    except Exception:
        await session.rollback()
        raise

    await session.refresh(approval)
    return approval


async def ensure_approval_resume_job(
    *,
    session: AsyncSession,
    approval: ApprovalRequest,
) -> None:
    existing = await session.scalar(
        select(ApprovalResumeJob.id).where(
            ApprovalResumeJob.approval_request_id == approval.id,
        )
    )

    if existing is not None:
        return

    session.add(
        ApprovalResumeJob(
            organization_id=approval.organization_id,
            incident_id=approval.incident_id,
            approval_request_id=approval.id,
            status=ApprovalResumeJobStatus.PENDING.value,
            attempts=0,
        )
    )
