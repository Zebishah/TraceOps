from langgraph.runtime import Runtime

from ops_pilot.ai.incident_analyzer import analyze_incident
from ops_pilot.ai.incident_recommender import recommend_incident_action
from ops_pilot.ai.incident_tool_selector import select_incident_tool
from ops_pilot.services.incident_classification import (
    classify_stored_incident,
)
from ops_pilot.services.incident_evidence import (
    retrieve_incident_evidence,
)
from ops_pilot.tools.executor import execute_operational_tool_call
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
        "classification_confidence": classification.confidence,
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
    )

    return {
        "recommended_action": recommendation,
    }


async def select_operational_tool_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    customer_id = state.get("subject_customer_id")

    if customer_id is None:
        return {
            "pending_tool_call": None,
            "needs_more_information": True,
            "clarification_question": (
                "Please provide or select the relevant order, transaction, "
                "product, amount, or approximate transaction date."
            ),
        }

    if (
        "title" not in state
        or "description" not in state
        or "category" not in state
        or "priority" not in state
        or "evidence" not in state
    ):
        raise RuntimeError("Tool selector received incomplete incident state")

    tool_round = state.get("tool_round", 0)

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
        tool_results=state.get("tool_results", []),
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
    customer_id = state.get("subject_customer_id")
    tool_call = state.get("pending_tool_call")

    if customer_id is None:
        raise RuntimeError("Tool execution requires customer context")

    if tool_call is None:
        raise RuntimeError("Tool execution requires a pending tool call")

    result = await execute_operational_tool_call(
        session=runtime.context.session,
        organization_id=state["organization_id"],
        customer_id=customer_id,
        tool_call=tool_call,
    )

    return {
        "tool_results": [
            *state.get("tool_results", []),
            result,
        ],
        "tool_round": state.get("tool_round", 0) + 1,
        "pending_tool_call": None,
    }


def route_after_tool_selection(
    state: IncidentInvestigationState,
) -> str:
    if state.get("pending_tool_call") is not None:
        return "execute_operational_tool"

    return "analyze_incident"
