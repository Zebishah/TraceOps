from langgraph.graph import END, START, StateGraph

from ops_pilot.workflows.incident.nodes import (
    analyze_incident_node,
    classify_incident_node,
    execute_operational_tool_node,
    recommend_action_node,
    retrieve_evidence_node,
    route_after_tool_selection,
    select_operational_tool_node,
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
    "select_operational_tool",
    select_operational_tool_node,
)

builder.add_node(
    "execute_operational_tool",
    execute_operational_tool_node,
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
    "select_operational_tool",
)

builder.add_conditional_edges(
    "select_operational_tool",
    route_after_tool_selection,
    {
        "execute_operational_tool": "execute_operational_tool",
        "analyze_incident": "analyze_incident",
    },
)

builder.add_edge(
    "execute_operational_tool",
    "select_operational_tool",
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
