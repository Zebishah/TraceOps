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
    detect_duplicate_payment_node,
    dispatch_customer_recovery_automation_node,
    dispatch_high_risk_automation_node,
    dispatch_incident_resolved_automation_node,
    execute_approved_action_node,
    execute_operational_tool_node,
    propose_action_node,
    recommend_action_node,
    retrieve_evidence_node,
    retrieve_memories_node,
    route_after_action_proposal,
    route_after_approval_decision,
    route_after_tool_selection,
    select_operational_tool_node,
    verify_approved_action_node,
    write_incident_memory_node,
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
    "dispatch_high_risk_automation",
    dispatch_high_risk_automation_node,
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
builder.add_node(
    "verify_approved_action",
    verify_approved_action_node,
)
builder.add_node(
    "retrieve_memories",
    retrieve_memories_node,
)
builder.add_node(
    "detect_duplicate_payment",
    detect_duplicate_payment_node,
)
builder.add_node(
    "write_incident_memory",
    write_incident_memory_node,
)
builder.add_node(
    "dispatch_customer_recovery_automation",
    dispatch_customer_recovery_automation_node,
)
builder.add_node(
    "dispatch_incident_resolved_automation",
    dispatch_incident_resolved_automation_node,
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
    "dispatch_high_risk_automation",
)

builder.add_edge(
    "dispatch_high_risk_automation",
    "retrieve_evidence",
)

builder.add_edge(
    "retrieve_evidence",
    "retrieve_memories",
)

builder.add_edge(
    "retrieve_memories",
    "select_operational_tool",
)


builder.add_conditional_edges(
    "select_operational_tool",
    route_after_tool_selection,
    {
        "needs_more_information": END,
        "execute_operational_tool": "execute_operational_tool",
        "analyze_incident": "detect_duplicate_payment",
    },
)

builder.add_edge(
    "detect_duplicate_payment",
    "analyze_incident",
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
    "verify_approved_action",
)

builder.add_edge(
    "verify_approved_action",
    "write_incident_memory",
)

builder.add_edge(
    "write_incident_memory",
    "dispatch_incident_resolved_automation",
)

builder.add_edge(
    "dispatch_incident_resolved_automation",
    "dispatch_customer_recovery_automation",
)

builder.add_edge(
    "dispatch_customer_recovery_automation",
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
