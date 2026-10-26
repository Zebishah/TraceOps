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

    # IMPORTANT:
    # Lock the incident FIRST, before looking for or
    # creating an approval.
    #
    # Manual resolution also locks this same incident.
    # This prevents approval creation and manual closure
    # from overwriting each other's state.
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
        raise RuntimeError("Incident not found while creating approval")

    # Never reopen a manually resolved incident.
    if incident.status == IncidentStatus.RESOLVED:
        await session.rollback()
        raise IncidentResolutionConflict("Cannot create approval for a resolved incident")

    # Only incidents actively being investigated or
    # awaiting approval are eligible.
    if incident.status not in {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.AWAITING_APPROVAL,
    }:
        await session.rollback()
        raise IncidentResolutionConflict("Incident is not eligible for approval creation")

    # Reuse an existing pending approval for this workflow.
    existing_result = await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.incident_id == incident_id,
            ApprovalRequest.workflow_thread_id == workflow_thread_id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
    )

    existing = existing_result.scalar_one_or_none()

    if existing is not None:
        # Release the incident lock after the read.
        await session.rollback()
        return existing

    approval = ApprovalRequest(
        organization_id=organization_id,
        incident_id=incident_id,
        workflow_thread_id=workflow_thread_id,
        action_type=proposal.action_type,
        action_payload={
            "external_transaction_id": proposal.external_transaction_id,
            "amount": str(proposal.amount),
            "currency": proposal.currency,
        },
        reason=proposal.reason,
        status=ApprovalStatus.PENDING,
    )

    incident.status = IncidentStatus.AWAITING_APPROVAL

    session.add(approval)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(approval)

    return approval


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
    if approval.status == desired_status or (
        approval.status == ApprovalStatus.EXECUTED and payload.approved
    ):
        await session.commit()
        await session.refresh(approval)
        return approval

    # Final decisions cannot be reversed.
    if approval.status != ApprovalStatus.PENDING:
        await session.rollback()
        raise ApprovalDecisionConflictError

    # A closed incident must never receive a new decision.
    if incident.status == IncidentStatus.RESOLVED:
        await session.rollback()
        raise IncidentResolutionConflict("Cannot decide approval for a resolved incident")

    if incident.status != IncidentStatus.AWAITING_APPROVAL:
        await session.rollback()
        raise IncidentResolutionConflict("Incident is not awaiting approval")

    approval.status = desired_status
    approval.decided_by_user_id = decided_by_user_id
    approval.decision_comment = payload.comment
    approval.decided_at = datetime.now(UTC)

    if not payload.approved:
        incident.status = IncidentStatus.INVESTIGATING

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(approval)

    return approval
