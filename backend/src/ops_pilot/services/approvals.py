import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.approval import (
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.incident import (
    Incident,
    IncidentStatus,
)
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
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
    ):
        raise ValueError(
            "Approval requires a complete action proposal",
        )

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
        return existing

    incident_result = await session.execute(
        select(Incident).where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
    )

    incident = incident_result.scalar_one_or_none()

    if incident is None:
        raise RuntimeError(
            "Incident not found while creating approval",
        )

    approval = ApprovalRequest(
        organization_id=organization_id,
        incident_id=incident_id,
        workflow_thread_id=workflow_thread_id,
        action_type=proposal.action_type,
        action_payload={
            "external_transaction_id": (proposal.external_transaction_id),
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
