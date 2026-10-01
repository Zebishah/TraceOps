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
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.workflows.incident.state import IncidentGraphContext


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
        tool_results,
    ):
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
        tool_results,
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
