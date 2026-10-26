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
from ops_pilot.models.approval import (
    ApprovalActionType,
)
from ops_pilot.models.incident import (
    Incident,
    IncidentStatus,
)
from ops_pilot.schemas.action_execution import RefundExecutionResult
from ops_pilot.schemas.approvals import (
    ApprovalResumeDecision,
)
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
)
from ops_pilot.schemas.incident_classification import (
    IncidentClassification,
)
from ops_pilot.schemas.incident_memories import IncidentMemoryRetrievalResult
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.services.approvals import (
    create_or_get_pending_approval,
)
from ops_pilot.services.automation_events import (
    dispatch_customer_recovery_automation,
    dispatch_high_risk_incident_automation,
    dispatch_incident_resolved_automation,
)
from ops_pilot.services.background_job_dispatch import (
    enqueue_memory_indexing,
)
from ops_pilot.services.duplicate_payment_detection import (
    detect_duplicate_payment_candidate,
)
from ops_pilot.services.incident_classification import (
    classify_stored_incident,
)
from ops_pilot.services.incident_evidence import (
    retrieve_incident_evidence,
)
from ops_pilot.services.incident_evidence_sufficiency import (
    has_required_operational_evidence,
)
from ops_pilot.services.incident_memories import generate_and_store_incident_memory
from ops_pilot.services.incident_memory_indexing import index_incident_memory
from ops_pilot.services.incident_memory_retrieval import (
    retrieve_similar_incident_memories,
)
from ops_pilot.services.incident_tool_planning import (
    required_operational_tool,
    tool_call_already_executed,
)
from ops_pilot.services.refund_execution import (
    execute_approved_refund,
)
from ops_pilot.services.refund_verification import (
    verify_refund_execution,
)
from ops_pilot.tools.executor import (
    execute_operational_tool_call,
)
from ops_pilot.tools.schemas import ToolExecutionResult
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
    IncidentInvestigationState,
)
from ops_pilot.workflows.observability import (
    observe_workflow_step,
)

MAX_TOOL_ROUNDS = 5


async def classify_incident_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    async def run_classification() -> tuple[
        Incident,
        IncidentClassification,
    ]:
        return await classify_stored_incident(
            session=runtime.context.session,
            organization_id=state["organization_id"],
            incident_id=state["incident_id"],
        )

    incident, classification = await observe_workflow_step(
        node="classify_incident",
        incident_id=state["incident_id"],
        workflow_thread_id=state.get("workflow_thread_id"),
        call=run_classification,
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


async def dispatch_high_risk_automation_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    priority = state.get("priority")

    if priority is None:
        return {
            "high_risk_automation_dispatched": False,
        }

    priority_value = priority.value if hasattr(priority, "value") else str(priority)

    if priority_value not in {
        "high",
        "critical",
    }:
        return {
            "high_risk_automation_dispatched": False,
        }

    title = state.get("title")

    if title is None:
        raise RuntimeError(
            "High-risk automation requires incident title",
        )

    category = state.get("category")

    category_value = (
        category.value
        if category is not None and hasattr(category, "value")
        else (str(category) if category is not None else None)
    )

    try:
        await dispatch_high_risk_incident_automation(
            organization_id=state["organization_id"],
            incident_id=state["incident_id"],
            title=title,
            priority=priority_value,
            category=category_value,
        )

    except Exception:
        return {
            "high_risk_automation_dispatched": False,
        }

    return {
        "high_risk_automation_dispatched": True,
    }


async def retrieve_evidence_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    async def run_retrieval() -> tuple[str, list[RetrievalResult]]:
        return await retrieve_incident_evidence(
            session=runtime.context.session,
            organization_id=state["organization_id"],
            incident_id=state["incident_id"],
        )

    query, evidence = await observe_workflow_step(
        node="retrieve_evidence",
        incident_id=state["incident_id"],
        workflow_thread_id=state.get("workflow_thread_id"),
        call=run_retrieval,
    )

    return {
        "retrieval_query": query,
        "evidence": evidence,
    }


async def retrieve_memories_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    if "title" not in state or "description" not in state or "category" not in state:
        raise RuntimeError(
            "Memory retrieval received incomplete incident state",
        )

    category = state["category"]

    category_value = (
        category.value
        if hasattr(
            category,
            "value",
        )
        else str(category)
    )

    async def run_memory_retrieval() -> list[IncidentMemoryRetrievalResult]:
        return await retrieve_similar_incident_memories(
            session=runtime.context.session,
            organization_id=state["organization_id"],
            current_incident_id=state["incident_id"],
            title=state["title"],
            description=state["description"],
            category=category_value,
        )

    memories = await observe_workflow_step(
        node="retrieve_memories",
        incident_id=state["incident_id"],
        workflow_thread_id=state.get("workflow_thread_id"),
        call=run_memory_retrieval,
    )

    return {
        "similar_memories": memories,
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

    async def run_analysis() -> str:
        return await analyze_incident(
            title=state["title"],
            description=state["description"],
            category=state["category"],
            priority=state["priority"],
            evidence=state["evidence"],
            memories=state.get(
                "similar_memories",
                [],
            ),
            duplicate_payment=state.get(
                "duplicate_payment_candidate",
            ),
            tool_results=state.get(
                "tool_results",
                [],
            ),
        )

    analysis = await observe_workflow_step(
        node="analyze_incident",
        incident_id=state["incident_id"],
        workflow_thread_id=state.get("workflow_thread_id"),
        call=run_analysis,
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

    async def run_recommendation() -> str:
        return await recommend_incident_action(
            title=state["title"],
            description=state["description"],
            category=state["category"],
            priority=state["priority"],
            analysis=state["analysis"],
            evidence=state["evidence"],
            memories=state.get(
                "similar_memories",
                [],
            ),
            duplicate_payment=state.get(
                "duplicate_payment_candidate",
            ),
            tool_results=state.get(
                "tool_results",
                [],
            ),
        )

    recommendation = await observe_workflow_step(
        node="recommend_action",
        incident_id=state["incident_id"],
        workflow_thread_id=state.get("workflow_thread_id"),
        call=run_recommendation,
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

    tool_results = state.get(
        "tool_results",
        [],
    )

    # Safety gate:
    # payment actions cannot be proposed
    # until required operational data
    # has been collected.
    if not has_required_operational_evidence(
        category=state["category"],
        tool_results=tool_results,
    ):
        return {
            "proposed_action": None,
            "approval_required": False,
        }

    duplicate_payment = state.get(
        "duplicate_payment_candidate",
    )

    # Security rule:
    # A payment refund must never be proposed through
    # the AI fallback when deterministic verification fails.
    if state["category"].value == "payment" and duplicate_payment is None:
        return {
            "proposed_action": None,
            "approval_required": False,
        }

    # Deterministic payment path:
    # if OpsPilot safely identified the exact
    # duplicate transaction, propose that refund.
    if state["category"].value == "payment" and duplicate_payment is not None:
        proposal = IncidentActionProposal(
            requires_approval=True,
            action_type=(ApprovalActionType.REFUND_TRANSACTION),
            external_transaction_id=(duplicate_payment.duplicate_transaction_id),
            amount=duplicate_payment.amount,
            currency=duplicate_payment.currency,
            reason=(
                "OpsPilot deterministically identified "
                f"{duplicate_payment.duplicate_transaction_id} "
                "as the later matching successful charge "
                f"for order {duplicate_payment.order_id}. "
                "Human approval is required before refund."
            ),
        )

        return {
            "proposed_action": proposal,
            "approval_required": True,
        }

    # Normal AI proposal path for cases where
    # there is no deterministic duplicate payment.
    proposal = await propose_incident_action(
        title=state["title"],
        description=state["description"],
        category=state["category"],
        priority=state["priority"],
        evidence=state["evidence"],
        tool_results=tool_results,
        analysis=state["analysis"],
        recommendation=state["recommended_action"],
    )

    return {
        "proposed_action": proposal,
        "approval_required": proposal.requires_approval,
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
        "status": IncidentStatus.AWAITING_APPROVAL,
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
        "status": IncidentStatus.AWAITING_APPROVAL,
    }


def approval_rejected_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    return {
        "approval_required": False,
        "status": IncidentStatus.INVESTIGATING,
    }


async def execute_approved_action_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    approval_request_id = state.get("approval_request_id")

    decision = state.get("approval_decision")

    customer_id = state.get("subject_customer_id")

    if approval_request_id is None:
        raise RuntimeError(
            "Approved action execution requires an approval request",
        )

    if decision is None or not decision.approved:
        raise RuntimeError(
            "Approved action execution requires an approved human decision",
        )

    if customer_id is None:
        raise RuntimeError(
            "Refund execution requires customer context",
        )

    async def run_approved_action() -> RefundExecutionResult:
        return await execute_approved_refund(
            session=runtime.context.session,
            organization_id=state["organization_id"],
            incident_id=state["incident_id"],
            approval_request_id=(approval_request_id),
            customer_id=customer_id,
        )

    result = await observe_workflow_step(
        node="execute_approved_action",
        incident_id=state["incident_id"],
        workflow_thread_id=state.get("workflow_thread_id"),
        call=run_approved_action,
    )

    return {
        "refund_execution": result,
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
                "Please provide or select "
                "the relevant order, "
                "transaction, product, "
                "amount, or approximate "
                "transaction date."
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

    tool_results = state.get(
        "tool_results",
        [],
    )

    tool_round = state.get(
        "tool_round",
        0,
    )

    required_tool_call = required_operational_tool(
        category=state["category"],
        tool_results=tool_results,
    )

    if required_tool_call is not None:
        return {
            "pending_tool_call": required_tool_call,
            "needs_more_information": False,
            "clarification_question": None,
        }

    if tool_round >= MAX_TOOL_ROUNDS:
        return {
            "pending_tool_call": None,
            "needs_more_information": False,
            "clarification_question": None,
        }

    # Required inspection is complete.
    # Qwen may now request an optional
    # additional read-only tool.
    tool_call = await select_incident_tool(
        title=state["title"],
        description=state["description"],
        category=state["category"],
        priority=state["priority"],
        evidence=state["evidence"],
        tool_results=tool_results,
    )

    # Never execute exactly the same
    # successful call twice.
    if tool_call is not None and tool_call_already_executed(
        tool_call=tool_call,
        tool_results=tool_results,
    ):
        return {
            "pending_tool_call": None,
            "needs_more_information": False,
            "clarification_question": None,
        }

    # THIS RETURN WAS MISSING IN YOUR CODE.
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

    async def run_tool_execution() -> ToolExecutionResult:
        return await execute_operational_tool_call(
            session=runtime.context.session,
            organization_id=state["organization_id"],
            customer_id=customer_id,
            tool_call=tool_call,
        )

    result = await observe_workflow_step(
        node="execute_operational_tool",
        incident_id=state["incident_id"],
        workflow_thread_id=state.get("workflow_thread_id"),
        call=run_tool_execution,
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


def detect_duplicate_payment_node(
    state: IncidentInvestigationState,
) -> dict[str, object]:
    category = state.get(
        "category",
    )

    if category is None:
        raise RuntimeError(
            "Duplicate payment detection requires incident category",
        )

    if category.value != "payment":
        return {
            "duplicate_payment_candidate": None,
        }

    candidate = detect_duplicate_payment_candidate(
        tool_results=state.get(
            "tool_results",
            [],
        ),
    )

    return {
        "duplicate_payment_candidate": candidate,
    }


def route_after_tool_selection(
    state: IncidentInvestigationState,
) -> str:
    if state.get("needs_more_information"):
        return "needs_more_information"

    if state.get("pending_tool_call") is not None:
        return "execute_operational_tool"

    return "analyze_incident"


async def verify_approved_action_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    approval_request_id = state.get("approval_request_id")

    execution = state.get("refund_execution")

    if approval_request_id is None:
        raise RuntimeError(
            "Refund verification requires approval request",
        )

    if execution is None:
        raise RuntimeError(
            "Refund verification requires execution result",
        )

    async def run_verification() -> None:
        await verify_refund_execution(
            session=runtime.context.session,
            organization_id=state["organization_id"],
            incident_id=state["incident_id"],
            approval_request_id=(approval_request_id),
            execution=execution,
        )

    await observe_workflow_step(
        node="verify_approved_action",
        incident_id=state["incident_id"],
        workflow_thread_id=state.get("workflow_thread_id"),
        call=run_verification,
    )

    return {
        "refund_verified": True,
        "status": IncidentStatus.RESOLVED,
    }


async def write_incident_memory_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    status = state.get(
        "status",
    )

    status_value = (
        status.value
        if isinstance(
            status,
            IncidentStatus,
        )
        else str(status)
    )

    if (
        status_value != IncidentStatus.RESOLVED.value
        or not state.get("refund_verified")
        or "title" not in state
        or "description" not in state
        or "category" not in state
        or "priority" not in state
        or "analysis" not in state
        or "recommended_action" not in state
    ):
        raise RuntimeError(
            "Memory writing requires a verified resolved incident",
        )

    try:
        memory = await generate_and_store_incident_memory(
            session=runtime.context.session,
            organization_id=(state["organization_id"]),
            incident_id=(state["incident_id"]),
            title=state["title"],
            description=state["description"],
            category=state["category"],
            priority=state["priority"],
            analysis=state["analysis"],
            recommendation=(state["recommended_action"]),
            tool_results=state.get(
                "tool_results",
                [],
            ),
            execution=state.get(
                "refund_execution",
            ),
        )

        memory_id = memory.id

    except Exception:
        return {
            "memory_id": None,
            "memory_indexed": False,
        }

    try:
        await index_incident_memory(
            session=runtime.context.session,
            organization_id=(state["organization_id"]),
            incident_id=(state["incident_id"]),
        )

    except Exception:
        try:
            await enqueue_memory_indexing(
                session=runtime.context.session,
                organization_id=(state["organization_id"]),
                incident_id=(state["incident_id"]),
            )
        except Exception:
            pass

        return {
            "memory_id": memory_id,
            "memory_indexed": False,
        }

    return {
        "memory_id": memory_id,
        "memory_indexed": True,
    }


async def dispatch_incident_resolved_automation_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    try:
        await dispatch_incident_resolved_automation(
            session=runtime.context.session,
            organization_id=state["organization_id"],
            incident_id=state["incident_id"],
        )

    except Exception:
        return {
            "automation_dispatched": False,
        }

    return {
        "automation_dispatched": True,
    }


async def dispatch_customer_recovery_automation_node(
    state: IncidentInvestigationState,
    runtime: Runtime[IncidentGraphContext],
) -> dict[str, object]:
    customer_id = state.get(
        "subject_customer_id",
    )

    execution = state.get(
        "refund_execution",
    )

    title = state.get(
        "title",
    )

    category = state.get(
        "category",
    )

    priority = state.get(
        "priority",
    )

    if (
        customer_id is None
        or execution is None
        or title is None
        or category is None
        or priority is None
        or not state.get("refund_verified")
    ):
        return {
            "customer_recovery_automation_dispatched": False,
        }

    category_value = category.value if hasattr(category, "value") else str(category)

    priority_value = priority.value if hasattr(priority, "value") else str(priority)

    try:
        await dispatch_customer_recovery_automation(
            session=runtime.context.session,
            organization_id=state["organization_id"],
            incident_id=state["incident_id"],
            title=title,
            category=category_value,
            priority=priority_value,
            customer_id=customer_id,
            execution=execution,
        )

    except Exception:
        return {
            "customer_recovery_automation_dispatched": False,
        }

    return {
        "customer_recovery_automation_dispatched": True,
    }
