"""Approval decision entry point.

Approval workflow execution belongs to the durable worker.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.approval import ApprovalRequest
from ops_pilot.schemas.approvals import ApprovalDecisionRequest
from ops_pilot.services.approvals import record_approval_decision


async def decide_and_resume_approval(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    decided_by_user_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
) -> ApprovalRequest:
    """Persist the approval decision and durable resume job.

    The legacy function name is retained for API compatibility.
    No LangGraph execution occurs in the API request.
    """
    return await record_approval_decision(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_request_id,
        decided_by_user_id=decided_by_user_id,
        payload=payload,
    )
