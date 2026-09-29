from langgraph.runtime import Runtime

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
