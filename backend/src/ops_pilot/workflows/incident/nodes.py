from langgraph.runtime import Runtime
from langgraph.types import interrupt

from ops_pilot.ai.incident_action_proposer import (
    propose_incident_action,
)
from ops_pilot.ai.incident_analyzer import analyze_incident
from ops_pilot.ai.incident_recommender import (
    recommend_incident_action,
)
from ops_pilot.ai.incident_tool_selector import (
    select_incident_tool,
)
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.schemas.approvals import (
    ApprovalResumeDecision,
)
from ops_pilot.services.approvals import (
    create_or_get_pending_approval,
)
from ops_pilot.services.incident_classification import (
    classify_stored_incident,
)
from ops_pilot.services.incident_evidence import (
    retrieve_incident_evidence,
)
from ops_pilot.tools.executor import (
    execute_operational_tool_call,
)
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
    IncidentInvestigationState,
)

MAX_TOOL_ROUNDS = 3


async def classify_incident_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    incident, classification = await classify_stored_incident(
        session=runtime.context.session,
        organization_id=state["organization_id"],
        incident_id=state["incident_id"],
    )

    return {
        "title": incident.title,
        "description": incident.description,
        "status": incident.status,
        "category": classification.category,
        "priority": classification.priority,
        "classification_confidence": (classification.confidence),
        "subject_customer_id": getattr(
            incident,
            "subject_customer_id",
            None,
        ),
    }


async def retrieve_evidence_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    query, evidence = await retrieve_incident_evidence(
        session=runtime.context.session,
        organization_id=state["organization_id"],
        incident_id=state["incident_id"],
    )

    return {
        "retrieval_query": query,
        "evidence": evidence,
    }


async def analyze_incident_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    if (
        "title" not in state
        or "description" not in state
        or "category" not in state
        or "priority" not in state
        or "evidence" not in state
    ):
        raise RuntimeError(
            "Analysis node received incomplete incident state",
        )

    analysis = await analyze_incident(
        title=state["title"],
        description=state["description"],
        category=state["category"],
        priority=state["priority"],
        evidence=state["evidence"],
        tool_results=state.get(
            "tool_results",
            [],
        ),
    )

    return {
        "analysis": analysis,
    }


async def recommend_action_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    if (
        "title" not in state
        or "description" not in state
        or "category" not in state
        or "priority" not in state
        or "evidence" not in state
        or "analysis" not in state
    ):
        raise RuntimeError(
            "Recommendation node received incomplete incident state",
        )

    recommendation = await recommend_incident_action(
        title=state["title"],
        description=state["description"],
        category=state["category"],
        priority=state["priority"],
        analysis=state["analysis"],
        evidence=state["evidence"],
        tool_results=state.get(
            "tool_results",
            [],
        ),
    )

    return {
        "recommended_action": recommendation,
    }


async def propose_action_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    if (
        "title" not in state
        or "description" not in state
        or "category" not in state
        or "priority" not in state
        or "evidence" not in state
        or "analysis" not in state
        or "recommended_action" not in state
    ):
        raise RuntimeError(
            "Action proposal node received incomplete incident state",
        )

    proposal = await propose_incident_action(
        title=state["title"],
        description=state["description"],
        category=state["category"],
        priority=state["priority"],
        evidence=state["evidence"],
        tool_results=state.get(
            "tool_results",
            [],
        ),
        analysis=state["analysis"],
        recommendation=state["recommended_action"],
    )

    return {
        "proposed_action": proposal,
        "approval_required": (proposal.requires_approval),
    }


def route_after_action_proposal(
    state: IncidentInvestigationState,
) -> str:
    if state.get("approval_required"):
        return "create_approval"

    return "end"


async def create_approval_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    proposal = state.get(
        "proposed_action",
    )

    if proposal is None:
        raise RuntimeError(
            "Approval creation requires a proposed action",
        )

    approval = await create_or_get_pending_approval(
        session=runtime.context.session,
        organization_id=state["organization_id"],
        incident_id=state["incident_id"],
        workflow_thread_id=state["workflow_thread_id"],
        proposal=proposal,
    )

    return {
        "approval_request_id": approval.id,
        "approval_required": True,
        "status": (IncidentStatus.AWAITING_APPROVAL),
    }


def approval_gate_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    approval_request_id = state.get(
        "approval_request_id",
    )

    proposal = state.get(
        "proposed_action",
    )

    if approval_request_id is None or proposal is None:
        raise RuntimeError(
            "Approval gate received incomplete approval state",
        )

    decision = interrupt(
        {
            "type": "approval_required",
            "approval_request_id": str(
                approval_request_id,
            ),
            "action_type": (
                proposal.action_type.value if proposal.action_type is not None else None
            ),
            "external_transaction_id": (proposal.external_transaction_id),
            "amount": (str(proposal.amount) if proposal.amount is not None else None),
            "currency": proposal.currency,
            "reason": proposal.reason,
        },
        response_schema=ApprovalResumeDecision,
    )

    if decision.approval_request_id != approval_request_id:
        raise RuntimeError(
            "Approval resume decision does not match the paused approval request",
        )

    return {
        "approval_decision": decision,
    }


def route_after_approval_decision(
    state: IncidentInvestigationState,
) -> str:
    decision = state.get(
        "approval_decision",
    )

    if decision is None:
        raise RuntimeError(
            "Approval routing requires a human decision",
        )

    if decision.approved:
        return "approved"

    return "rejected"


def approval_approved_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    return {
        "approval_required": False,
        # The action is approved but has NOT
        # been executed yet.
        # Phase 8E will execute it.
        "status": (IncidentStatus.AWAITING_APPROVAL),
    }


def approval_rejected_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    return {
        "approval_required": False,
        "status": IncidentStatus.INVESTIGATING,
    }


async def select_operational_tool_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    customer_id = state.get(
        "subject_customer_id",
    )

    if customer_id is None:
        return {
            "pending_tool_call": None,
            "needs_more_information": True,
            "clarification_question": (
                "Please provide or select the relevant "
                "order, transaction, product, amount, "
                "or approximate transaction date."
            ),
        }

    if (
        "title" not in state
        or "description" not in state
        or "category" not in state
        or "priority" not in state
        or "evidence" not in state
    ):
        raise RuntimeError(
            "Tool selector received incomplete incident state",
        )

    tool_round = state.get(
        "tool_round",
        0,
    )

    if tool_round >= MAX_TOOL_ROUNDS:
        return {
            "pending_tool_call": None,
        }

    tool_call = await select_incident_tool(
        title=state["title"],
        description=state["description"],
        category=state["category"],
        priority=state["priority"],
        evidence=state["evidence"],
        tool_results=state.get(
            "tool_results",
            [],
        ),
    )

    return {
        "pending_tool_call": tool_call,
        "needs_more_information": False,
        "clarification_question": None,
    }


async def execute_operational_tool_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    customer_id = state.get(
        "subject_customer_id",
    )

    tool_call = state.get(
        "pending_tool_call",
    )

    if customer_id is None:
        raise RuntimeError(
            "Tool execution requires customer context",
        )

    if tool_call is None:
        raise RuntimeError(
            "Tool execution requires a pending tool call",
        )

    result = await execute_operational_tool_call(
        session=runtime.context.session,
        organization_id=state["organization_id"],
        customer_id=customer_id,
        tool_call=tool_call,
    )

    return {
        "tool_results": [
            *state.get(
                "tool_results",
                [],
            ),
            result,
        ],
        "tool_round": (
            state.get(
                "tool_round",
                0,
            )
            + 1
        ),
        "pending_tool_call": None,
    }


def route_after_tool_selection(
    state: IncidentInvestigationState,
) -> str:
    if state.get("needs_more_information"):
        return "needs_more_information"

    if state.get("pending_tool_call") is not None:
        return "execute_operational_tool"

    return "analyze_incident"
