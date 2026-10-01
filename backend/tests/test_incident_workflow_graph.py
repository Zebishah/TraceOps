import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.workflows.incident.nodes as nodes_module
from ops_pilot.models.incident import (
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
)
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
    IncidentClassification,
)
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolExecutionResult,
)
from ops_pilot.workflows.incident.graph import (
    incident_investigation_graph,
)
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
)


def test_incident_investigation_graph_runs_in_order(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    workflow_thread_id = "test-workflow-thread"

    call_order: list[str] = []

    incident = SimpleNamespace(
        title="Customer charged twice",
        description=("Two charges appeared for one order."),
        status=IncidentStatus.INVESTIGATING,
        subject_customer_id=customer_id,
    )

    classification = IncidentClassification(
        category=IncidentCategory.PAYMENT,
        priority=IncidentPriority.HIGH,
        confidence=0.98,
    )

    evidence = [
        RetrievalResult(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=0,
            page_number=2,
            text=("Duplicate payments must be verified before a refund is issued."),
            source_filename="payment-policy.pdf",
            vector_score=0.91,
            reranker_score=0.97,
        )
    ]

    order_id = "ORD-TEST-123"

    async def fake_classify_stored_incident(
        *,
        session,
        organization_id,
        incident_id,
    ):
        call_order.append("classify")

        return incident, classification

    async def fake_retrieve_incident_evidence(
        *,
        session,
        organization_id,
        incident_id,
    ):
        call_order.append("retrieve")

        return (
            ("Customer charged twice\nIncident category: payment"),
            evidence,
        )

    async def fake_execute_operational_tool_call(
        *,
        session,
        organization_id,
        customer_id,
        tool_call,
    ):
        if tool_call.tool_name == OperationalToolName.LIST_CUSTOMER_ORDERS:
            call_order.append("list_customer_orders")

            return ToolExecutionResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                arguments=dict(tool_call.arguments),
                success=True,
                content=json.dumps(
                    [
                        {
                            "external_order_id": (order_id),
                            "product_name": ("Test Product"),
                            "total_amount": ("12000.00"),
                            "currency": "PKR",
                            "status": "paid",
                            "ordered_at": ("2026-10-01T10:00:00Z"),
                        }
                    ]
                ),
            )

        if tool_call.tool_name == OperationalToolName.LIST_ORDER_PAYMENTS:
            call_order.append("list_order_payments")

            return ToolExecutionResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                arguments=dict(tool_call.arguments),
                success=True,
                content=json.dumps(
                    [
                        {
                            "external_transaction_id": ("TXN-A"),
                            "provider": "stripe",
                            "transaction_type": ("charge"),
                            "amount": "12000.00",
                            "currency": "PKR",
                            "status": "succeeded",
                            "processed_at": ("2026-10-01T10:01:00Z"),
                        },
                        {
                            "external_transaction_id": ("TXN-B"),
                            "provider": "stripe",
                            "transaction_type": ("charge"),
                            "amount": "12000.00",
                            "currency": "PKR",
                            "status": "succeeded",
                            "processed_at": ("2026-10-01T10:02:00Z"),
                        },
                    ]
                ),
            )

        raise AssertionError("Unexpected operational tool call")

    async def fake_select_incident_tool(
        *,
        title,
        description,
        category,
        priority,
        evidence,
        tool_results,
    ):
        call_order.append("select_optional_tool")

        return None

    async def fake_analyze_incident(
        *,
        title,
        description,
        category,
        priority,
        evidence,
        tool_results,
    ):
        call_order.append("analyze")

        return "The evidence supports a duplicate payment [SOURCE 1]."

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
        call_order.append("recommend")

        return "Verify the transactions before issuing a refund [SOURCE 1]."

    async def fake_propose_incident_action(
        *,
        title,
        description,
        category,
        priority,
        evidence,
        tool_results,
        analysis,
        recommendation,
    ):
        call_order.append("propose_action")

        return IncidentActionProposal(
            requires_approval=False,
            action_type=None,
            external_transaction_id=None,
            amount=None,
            currency=None,
            reason=("More verification is required."),
        )

    monkeypatch.setattr(
        nodes_module,
        "classify_stored_incident",
        fake_classify_stored_incident,
    )

    monkeypatch.setattr(
        nodes_module,
        "retrieve_incident_evidence",
        fake_retrieve_incident_evidence,
    )

    monkeypatch.setattr(
        nodes_module,
        "execute_operational_tool_call",
        fake_execute_operational_tool_call,
    )

    monkeypatch.setattr(
        nodes_module,
        "select_incident_tool",
        fake_select_incident_tool,
    )

    monkeypatch.setattr(
        nodes_module,
        "analyze_incident",
        fake_analyze_incident,
    )

    monkeypatch.setattr(
        nodes_module,
        "recommend_incident_action",
        fake_recommend_incident_action,
    )

    monkeypatch.setattr(
        nodes_module,
        "propose_incident_action",
        fake_propose_incident_action,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    result = asyncio.run(
        incident_investigation_graph.ainvoke(
            {
                "organization_id": (organization_id),
                "incident_id": incident_id,
                "workflow_thread_id": (workflow_thread_id),
            },
            context=IncidentGraphContext(
                session=session,
            ),
        )
    )

    assert call_order == [
        "classify",
        "retrieve",
        "list_customer_orders",
        "list_order_payments",
        "select_optional_tool",
        "analyze",
        "recommend",
        "propose_action",
    ]

    assert result["organization_id"] == organization_id

    assert result["incident_id"] == incident_id

    assert result["workflow_thread_id"] == workflow_thread_id

    assert result["title"] == "Customer charged twice"

    assert result["category"] == IncidentCategory.PAYMENT

    assert result["priority"] == IncidentPriority.HIGH

    assert result["evidence"] == evidence

    assert result["analysis"] == ("The evidence supports a duplicate payment [SOURCE 1].")

    assert result["recommended_action"] == (
        "Verify the transactions before issuing a refund [SOURCE 1]."
    )
