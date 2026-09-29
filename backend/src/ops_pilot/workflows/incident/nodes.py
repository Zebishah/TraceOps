from langgraph.runtime import Runtime

from ops_pilot.ai.incident_analyzer import analyze_incident
from ops_pilot.ai.incident_recommender import recommend_incident_action
from ops_pilot.services.incident_classification import (
    classify_stored_incident,
)
from ops_pilot.services.incident_evidence import (
    retrieve_incident_evidence,
)
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
    IncidentInvestigationState,
)


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
