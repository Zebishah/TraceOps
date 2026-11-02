import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.workflows.incident.nodes as nodes
from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
    IncidentClassification,
)
from ops_pilot.schemas.incidents import IncidentInvestigationResponse
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)
from ops_pilot.workflows.incident.state import IncidentGraphContext


@pytest.mark.asyncio
async def test_missing_customer_skips_retrieval_and_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    incident = SimpleNamespace(
        title="Missing payment details",
        description="Customer identity has not been supplied.",
        status=IncidentStatus.INVESTIGATING,
        subject_customer_id=None,
    )
    classification = IncidentClassification(
        category=IncidentCategory.PAYMENT,
        priority=IncidentPriority.MEDIUM,
        confidence=0.95,
    )

    classify = AsyncMock(return_value=(incident, classification))
    retrieve = AsyncMock()
    memories = AsyncMock()
    analyze = AsyncMock()
    recommend = AsyncMock()
    select_tool = AsyncMock()

    monkeypatch.setattr(nodes, "classify_stored_incident", classify)
    monkeypatch.setattr(nodes, "retrieve_incident_evidence", retrieve)
    monkeypatch.setattr(nodes, "retrieve_similar_incident_memories", memories)
    monkeypatch.setattr(nodes, "analyze_incident", analyze)
    monkeypatch.setattr(nodes, "recommend_incident_action", recommend)
    monkeypatch.setattr(nodes, "select_incident_tool", select_tool)

    graph = build_incident_investigation_graph()
    result = await graph.ainvoke(
        {
            "organization_id": organization_id,
            "incident_id": incident_id,
            "workflow_thread_id": "missing-customer-test",
        },
        context=IncidentGraphContext(
            session=cast(AsyncSession, AsyncMock()),
        ),
    )

    response = IncidentInvestigationResponse.model_validate(result)

    assert response.needs_more_information is True
    assert response.clarification_question == nodes.CUSTOMER_CONTEXT_QUESTION
    assert response.approval_required is False
    assert response.approval_request_id is None
    assert response.evidence == []
    assert response.similar_memories == []
    assert response.tool_results == []

    classify.assert_awaited_once()
    retrieve.assert_not_awaited()
    memories.assert_not_awaited()
    analyze.assert_not_awaited()
    recommend.assert_not_awaited()
    select_tool.assert_not_awaited()
