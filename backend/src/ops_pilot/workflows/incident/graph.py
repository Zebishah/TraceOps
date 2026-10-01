from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from ops_pilot.workflows.incident.nodes import (
    analyze_incident_node,
    approval_approved_node,
    approval_gate_node,
    approval_rejected_node,
    classify_incident_node,
    create_approval_node,
    execute_approved_action_node,
    execute_operational_tool_node,
    propose_action_node,
    recommend_action_node,
    retrieve_evidence_node,
    route_after_action_proposal,
    route_after_approval_decision,
    route_after_tool_selection,
    select_operational_tool_node,
)
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
    IncidentInvestigationState,
)

type IncidentCompiledGraph = CompiledStateGraph[
    IncidentInvestigationState,
    IncidentGraphContext,
    IncidentInvestigationState,
    IncidentInvestigationState,
]


builder = StateGraph(
    IncidentInvestigationState,
    context_schema=IncidentGraphContext,
)


# -------------------------
# Register nodes
# -------------------------

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

builder.add_node(
    "propose_action",
    propose_action_node,
)

builder.add_node(
    "create_approval",
    create_approval_node,
)

builder.add_node(
    "approval_gate",
    approval_gate_node,
)
builder.add_node(
    "approval_approved",
    approval_approved_node,
)

builder.add_node(
    "approval_rejected",
    approval_rejected_node,
)
builder.add_node(
    "execute_approved_action",
    execute_approved_action_node,
)
# -------------------------
# Investigation flow
# -------------------------

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
        "needs_more_information": END,
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


# -------------------------
# HITL flow
# -------------------------

builder.add_edge(
    "recommend_action",
    "propose_action",
)


builder.add_conditional_edges(
    "propose_action",
    route_after_action_proposal,
    {
        "create_approval": "create_approval",
        "end": END,
    },
)


builder.add_edge(
    "create_approval",
    "approval_gate",
)
builder.add_conditional_edges(
    "approval_gate",
    route_after_approval_decision,
    {
        "approved": "approval_approved",
        "rejected": "approval_rejected",
    },
)

builder.add_edge(
    "approval_approved",
    "execute_approved_action",
)

builder.add_edge(
    "execute_approved_action",
    END,
)

builder.add_edge(
    "approval_rejected",
    END,
)

# -------------------------
# Compilation
# -------------------------


def build_incident_investigation_graph(
    *,
    checkpointer: Checkpointer = None,
) -> IncidentCompiledGraph:
    return builder.compile(
        checkpointer=checkpointer,
    )


incident_investigation_graph = build_incident_investigation_graph()
