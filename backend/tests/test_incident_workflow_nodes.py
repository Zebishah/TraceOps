import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import ops_pilot.workflows.incident.nodes as nodes_module
from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
    IncidentClassification,
)
from ops_pilot.schemas.retrieval import RetrievalResult


def test_classify_incident_node_updates_state(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

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

    session = AsyncMock()

    runtime = SimpleNamespace(
        context=SimpleNamespace(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.classify_incident_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
            },
            runtime,
        )
    )

    assert result["title"] == "Customer charged twice"
    assert result["category"] == IncidentCategory.PAYMENT
    assert result["priority"] == IncidentPriority.HIGH
    assert result["classification_confidence"] == 0.98
    assert result["status"] == IncidentStatus.INVESTIGATING


def test_retrieve_evidence_node_updates_state(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    expected_result = RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=2,
        page_number=3,
        text="Duplicate payments must be refunded after verification.",
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

    session = AsyncMock()

    runtime = SimpleNamespace(
        context=SimpleNamespace(
            session=session,
        )
    )

    result = asyncio.run(
        nodes_module.retrieve_evidence_node(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
            },
            runtime,
        )
    )

    assert result["retrieval_query"] == "Customer charged twice\nIncident category: payment"

    assert result["evidence"] == [expected_result]
