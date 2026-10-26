import uuid

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import ApprovalDecisionConflictError
from ops_pilot.models.approval import (
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.schemas.approvals import (
    ApprovalDecisionRequest,
    ApprovalResumeDecision,
)
from ops_pilot.services.approvals import (
    get_approval_request,
    record_approval_decision,
)
from ops_pilot.workflows.incident.checkpointing import (
    open_incident_checkpointer,
)
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
)


async def decide_and_resume_approval(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    decided_by_user_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
) -> ApprovalRequest:
    existing_approval = await get_approval_request(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_request_id,
    )

    if existing_approval.status == ApprovalStatus.EXECUTED:
        await session.rollback()
        return existing_approval

    config: RunnableConfig = {
        "configurable": {
            "thread_id": existing_approval.workflow_thread_id,
        }
    }

    # Verify the workflow is paused at its human approval gate.
    try:
        async with open_incident_checkpointer() as checkpointer:
            graph = build_incident_investigation_graph(
                checkpointer=checkpointer,
            )
            snapshot = await graph.aget_state(config)

        paused_for_approval = any(
            task.name == "approval_gate" and bool(task.interrupts) for task in snapshot.tasks
        )
    except Exception:
        await session.rollback()
        raise

    if not paused_for_approval:
        await session.rollback()
        raise ApprovalDecisionConflictError("Workflow is not waiting for an approval decision")

    # Release the read transaction before starting the decision.
    await session.rollback()

    approval = await record_approval_decision(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_request_id,
        decided_by_user_id=decided_by_user_id,
        payload=payload,
    )

    if approval.status == ApprovalStatus.EXECUTED:
        return approval

    if approval.decided_by_user_id is None:
        raise RuntimeError("Recorded approval is missing reviewer identity")

    decision = ApprovalResumeDecision(
        approval_request_id=approval.id,
        approved=(approval.status == ApprovalStatus.APPROVED),
        decided_by_user_id=approval.decided_by_user_id,
        comment=approval.decision_comment,
    )

    try:
        async with open_incident_checkpointer() as checkpointer:
            graph = build_incident_investigation_graph(
                checkpointer=checkpointer,
            )

            await graph.ainvoke(
                Command(
                    resume=decision.model_dump(mode="json"),
                ),
                config=config,
                context=IncidentGraphContext(session=session),
            )
    except Exception:
        await session.rollback()
        raise

    await session.refresh(approval)
    return approval
