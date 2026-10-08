import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.workflows.incident.nodes as nodes_module
from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.models.incident_memory import IncidentMemory
from ops_pilot.schemas.action_execution import (
    RefundExecutionResult,
)
from ops_pilot.schemas.approvals import (
    ApprovalResumeDecision,
)
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
    IncidentClassification,
)
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryRetrievalResult,
)
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
)


def test_classify_incident_node_updates_state(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    workflow_thread_id = "test-workflow-thread"

    incident = SimpleNamespace(
        title="Customer charged twice",
        description="Customer was charged twice for one order.",
        status=IncidentStatus.INVESTIGATING,
    )

    classification = IncidentClassification(
        category=IncidentCategory.PAYMENT,
        priority=IncidentPriority.HIGH,
        confidence=0.98,
    )

    async def fake_classify_stored_incident(
        *,
        session,
        organization_id,
        incident_id,
    ):
        return incident, classification

    monkeypatch.setattr(
        nodes_module,
        "classify_stored_incident",
        fake_classify_stored_incident,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.classify_incident_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": workflow_thread_id,
            },
            runtime,
        )
    )

    assert result["title"] == "Customer charged twice"
    assert result["category"] == IncidentCategory.PAYMENT
    assert result["priority"] == IncidentPriority.HIGH
    assert result["classification_confidence"] == 0.98
    assert result["status"] == IncidentStatus.INVESTIGATING


def test_analyze_incident_node_updates_state(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    workflow_thread_id = "test-workflow-thread"

    evidence = [
        RetrievalResult(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=1,
            page_number=4,
            text="Duplicate transactions require verification.",
            source_filename="payments.pdf",
            vector_score=0.90,
            reranker_score=0.95,
        )
    ]

    async def fake_analyze_incident(
        *,
        title,
        description,
        category,
        priority,
        evidence,
        memories,
        tool_results,
        duplicate_payment,
    ):
        return "The evidence supports a duplicate payment [SOURCE 1]."
        return "The evidence supports a duplicate payment [SOURCE 1]."

    monkeypatch.setattr(
        nodes_module,
        "analyze_incident",
        fake_analyze_incident,
    )

    result = asyncio.run(
        nodes_module.analyze_incident_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": workflow_thread_id,
                "title": "Customer charged twice",
                "description": ("Customer reports two charges for one order."),
                "status": IncidentStatus.INVESTIGATING,
                "category": IncidentCategory.PAYMENT,
                "priority": IncidentPriority.HIGH,
                "classification_confidence": 0.98,
                "retrieval_query": "Customer charged twice",
                "evidence": evidence,
            }
        )
    )

    assert result["analysis"] == ("The evidence supports a duplicate payment [SOURCE 1].")


def test_recommend_action_node_updates_state(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    workflow_thread_id = "test-workflow-thread"

    evidence = [
        RetrievalResult(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=1,
            page_number=4,
            text="Duplicate transactions require verification.",
            source_filename="payments.pdf",
            vector_score=0.90,
            reranker_score=0.95,
        )
    ]

    async def fake_recommend_incident_action(
        *,
        title,
        description,
        category,
        priority,
        analysis,
        evidence,
        memories,
        tool_results,
        duplicate_payment,
    ):
        return "Verify the transactions before issuing a refund [SOURCE 1]."

    monkeypatch.setattr(
        nodes_module,
        "recommend_incident_action",
        fake_recommend_incident_action,
    )

    result = asyncio.run(
        nodes_module.recommend_action_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": workflow_thread_id,
                "title": "Customer charged twice",
                "description": ("Two charges appeared for one order."),
                "status": IncidentStatus.INVESTIGATING,
                "category": IncidentCategory.PAYMENT,
                "priority": IncidentPriority.HIGH,
                "classification_confidence": 0.98,
                "retrieval_query": "Customer charged twice",
                "evidence": evidence,
                "analysis": ("The evidence supports a duplicate payment [SOURCE 1]."),
            }
        )
    )

    assert result["recommended_action"] == (
        "Verify the transactions before issuing a refund [SOURCE 1]."
    )


def test_retrieve_evidence_node_updates_state(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    workflow_thread_id = "test-workflow-thread"

    expected_result = RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=2,
        page_number=3,
        text=("Duplicate payments must be refunded after verification."),
        source_filename="payment-policy.pdf",
        vector_score=0.91,
        reranker_score=0.96,
    )

    async def fake_retrieve_incident_evidence(
        *,
        session,
        organization_id,
        incident_id,
    ):
        return (
            "Customer charged twice\nIncident category: payment",
            [expected_result],
        )

    monkeypatch.setattr(
        nodes_module,
        "retrieve_incident_evidence",
        fake_retrieve_incident_evidence,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.retrieve_evidence_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": workflow_thread_id,
            },
            runtime,
        )
    )

    assert result["retrieval_query"] == ("Customer charged twice\nIncident category: payment")

    assert result["evidence"] == [expected_result]


def test_route_after_action_proposal_requires_approval() -> None:
    result = nodes_module.route_after_action_proposal(
        {
            "organization_id": uuid.uuid4(),
            "incident_id": uuid.uuid4(),
            "workflow_thread_id": "test-thread",
            "approval_required": True,
        }
    )

    assert result == "create_approval"


def test_route_after_approval_decision_approved() -> None:
    result = nodes_module.route_after_approval_decision(
        {
            "organization_id": uuid.uuid4(),
            "incident_id": uuid.uuid4(),
            "workflow_thread_id": "test-thread",
            "approval_decision": (
                ApprovalResumeDecision(
                    approval_request_id=(uuid.uuid4()),
                    approved=True,
                    decided_by_user_id=(uuid.uuid4()),
                    comment=None,
                )
            ),
        }
    )

    assert result == "approved"


def test_route_after_approval_decision_rejected() -> None:
    result = nodes_module.route_after_approval_decision(
        {
            "organization_id": uuid.uuid4(),
            "incident_id": uuid.uuid4(),
            "workflow_thread_id": "test-thread",
            "approval_decision": (
                ApprovalResumeDecision(
                    approval_request_id=(uuid.uuid4()),
                    approved=False,
                    decided_by_user_id=(uuid.uuid4()),
                    comment="Do not refund.",
                )
            ),
        }
    )

    assert result == "rejected"


def test_route_after_action_proposal_ends_without_action() -> None:
    result = nodes_module.route_after_action_proposal(
        {
            "organization_id": uuid.uuid4(),
            "incident_id": uuid.uuid4(),
            "workflow_thread_id": "test-thread",
            "approval_required": False,
        }
    )

    assert result == "end"


def test_execute_approved_action_node_executes_refund(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    approval_request_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()

    expected_result = RefundExecutionResult(
        source_transaction_id="TXN-123",
        refund_transaction_id="refund-123",
        amount=Decimal("12000.00"),
        currency="PKR",
        already_executed=False,
    )

    async def fake_execute_approved_refund(
        *,
        session,
        organization_id,
        incident_id,
        approval_request_id,
        customer_id,
    ):
        assert organization_id == (expected_organization_id)

        assert incident_id == (expected_incident_id)

        assert approval_request_id == (expected_approval_request_id)

        assert customer_id == (expected_customer_id)

        return expected_result

    expected_organization_id = organization_id
    expected_incident_id = incident_id
    expected_approval_request_id = approval_request_id
    expected_customer_id = customer_id

    monkeypatch.setattr(
        nodes_module,
        "execute_approved_refund",
        fake_execute_approved_refund,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.execute_approved_action_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": ("test-thread"),
                "subject_customer_id": customer_id,
                "approval_request_id": (approval_request_id),
                "approval_decision": (
                    ApprovalResumeDecision(
                        approval_request_id=(approval_request_id),
                        approved=True,
                        decided_by_user_id=(reviewer_id),
                        comment="Approved refund.",
                    )
                ),
            },
            runtime,
        )
    )

    assert result["refund_execution"] == expected_result


def test_verify_approved_action_node_marks_resolved(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    approval_request_id = uuid.uuid4()

    execution = RefundExecutionResult(
        source_transaction_id="TXN-123",
        refund_transaction_id="refund-123",
        amount=Decimal("12000.00"),
        currency="PKR",
        already_executed=False,
    )

    async def fake_verify_refund_execution(
        *,
        session,
        organization_id,
        incident_id,
        approval_request_id,
        execution,
    ):
        assert organization_id == (expected_organization_id)
        assert incident_id == (expected_incident_id)
        assert approval_request_id == (expected_approval_request_id)
        assert execution == expected_execution

    expected_organization_id = organization_id
    expected_incident_id = incident_id
    expected_approval_request_id = approval_request_id
    expected_execution = execution

    monkeypatch.setattr(
        nodes_module,
        "verify_refund_execution",
        fake_verify_refund_execution,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.verify_approved_action_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": ("test-thread"),
                "approval_request_id": (approval_request_id),
                "refund_execution": execution,
            },
            runtime,
        )
    )

    assert result["refund_verified"] is True

    assert result["status"] == IncidentStatus.RESOLVED


def test_retrieve_memories_node_updates_state(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    memory_id = uuid.uuid4()
    previous_incident_id = uuid.uuid4()

    expected = [
        IncidentMemoryRetrievalResult(
            memory_id=memory_id,
            incident_id=previous_incident_id,
            subject_customer_id=None,
            category="payment",
            summary=("A previous customer was charged twice."),
            resolution=("The duplicate charge was refunded."),
            vector_score=0.92,
        )
    ]

    async def fake_retrieve_similar_incident_memories(
        **kwargs: object,
    ) -> list[IncidentMemoryRetrievalResult]:
        assert kwargs["organization_id"] == organization_id

        assert kwargs["current_incident_id"] == incident_id

        assert kwargs["category"] == "payment"

        assert "session" in kwargs

        return expected

    monkeypatch.setattr(
        nodes_module,
        "retrieve_similar_incident_memories",
        fake_retrieve_similar_incident_memories,
    )

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.retrieve_memories_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": "test-thread",
                "title": "Customer charged twice",
                "description": ("Two charges for one order."),
                "category": (IncidentCategory.PAYMENT),
            },
            runtime,
        )
    )

    assert result["similar_memories"] == expected


def test_write_incident_memory_node_persists_and_indexes(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    memory_id = uuid.uuid4()

    memory = IncidentMemory(
        id=memory_id,
        organization_id=organization_id,
        incident_id=incident_id,
        subject_customer_id=None,
        category="payment",
        summary="Duplicate payment confirmed.",
        resolution="Duplicate charge refunded.",
    )

    async def fake_generate_and_store_incident_memory(
        **kwargs: object,
    ) -> IncidentMemory:
        return memory

    async def fake_index_incident_memory(
        **kwargs: object,
    ) -> int:
        return 1

    monkeypatch.setattr(
        nodes_module,
        "generate_and_store_incident_memory",
        fake_generate_and_store_incident_memory,
    )

    monkeypatch.setattr(
        nodes_module,
        "index_incident_memory",
        fake_index_incident_memory,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.write_incident_memory_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": "test-thread",
                "title": "Customer charged twice",
                "description": "Two charges appeared.",
                "status": IncidentStatus.RESOLVED,
                "category": IncidentCategory.PAYMENT,
                "priority": IncidentPriority.HIGH,
                "analysis": "Duplicate payment confirmed.",
                "recommended_action": "Refund duplicate charge.",
                "refund_verified": True,
                "tool_results": [],
            },
            runtime,
        )
    )

    assert result["memory_id"] == memory_id
    assert result["memory_indexed"] is True


def test_write_incident_memory_node_enqueues_retry_when_indexing_fails(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    memory_id = uuid.uuid4()

    memory = IncidentMemory(
        id=memory_id,
        organization_id=organization_id,
        incident_id=incident_id,
        subject_customer_id=None,
        category="payment",
        summary="Duplicate payment confirmed.",
        resolution="Duplicate charge refunded.",
    )

    async def fake_generate_and_store_incident_memory(
        **kwargs: object,
    ) -> IncidentMemory:
        return memory

    async def fake_index_incident_memory(
        **kwargs: object,
    ) -> int:
        raise RuntimeError("Qdrant unavailable")

    enqueue_mock = AsyncMock()

    monkeypatch.setattr(
        nodes_module,
        "generate_and_store_incident_memory",
        fake_generate_and_store_incident_memory,
    )

    monkeypatch.setattr(
        nodes_module,
        "index_incident_memory",
        fake_index_incident_memory,
    )

    monkeypatch.setattr(
        nodes_module,
        "enqueue_memory_indexing",
        enqueue_mock,
    )

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.write_incident_memory_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": "test-thread",
                "title": "Customer charged twice",
                "description": "Two charges appeared.",
                "status": IncidentStatus.RESOLVED,
                "category": IncidentCategory.PAYMENT,
                "priority": IncidentPriority.HIGH,
                "analysis": "Duplicate payment confirmed.",
                "recommended_action": ("Refund duplicate charge."),
                "refund_verified": True,
                "tool_results": [],
            },
            runtime,
        )
    )

    assert result["memory_id"] == memory_id
    assert result["memory_indexed"] is False

    enqueue_mock.assert_awaited_once_with(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )


def test_dispatch_incident_resolved_automation_node(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    dispatch_mock = AsyncMock()

    monkeypatch.setattr(
        nodes_module,
        "dispatch_incident_resolved_automation",
        dispatch_mock,
    )

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.dispatch_incident_resolved_automation_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": "test-thread",
            },
            runtime,
        )
    )

    assert result == {
        "automation_dispatched": True,
    }

    dispatch_mock.assert_awaited_once_with(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )


def test_dispatch_incident_resolved_automation_failure_is_non_fatal(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    dispatch_mock = AsyncMock(side_effect=RuntimeError("n8n unavailable"))

    monkeypatch.setattr(
        nodes_module,
        "dispatch_incident_resolved_automation",
        dispatch_mock,
    )

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    runtime = Runtime[IncidentGraphContext](
        context=IncidentGraphContext(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.dispatch_incident_resolved_automation_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": "test-thread",
            },
            runtime,
        )
    )

    assert result == {
        "automation_dispatched": False,
    }
