from langgraph.graph import END, START, StateGraph

from ops_pilot.workflows.incident.nodes import (
    analyze_incident_node,
    classify_incident_node,
    recommend_action_node,
    retrieve_evidence_node,
)
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
    IncidentInvestigationState,
)

builder = StateGraph(
    IncidentInvestigationState,
    context_schema=IncidentGraphContext,
)

builder.add_node(
    "classify_incident",
    classify_incident_node,
)

builder.add_node(
    "retrieve_evidence",
    retrieve_evidence_node,
)

builder.add_node(
    "analyze_incident",
    analyze_incident_node,
)

builder.add_node(
    "recommend_action",
    recommend_action_node,
)

builder.add_edge(
    START,
    "classify_incident",
)

builder.add_edge(
    "classify_incident",
    "retrieve_evidence",
)

builder.add_edge(
    "retrieve_evidence",
    "analyze_incident",
)

builder.add_edge(
    "analyze_incident",
    "recommend_action",
)

builder.add_edge(
    "recommend_action",
    END,
)

incident_investigation_graph = builder.compile()
