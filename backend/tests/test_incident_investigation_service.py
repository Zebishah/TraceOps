import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.incident_investigation as investigation_module
from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.schemas.retrieval import RetrievalResult


def test_investigate_incident_runs_checkpointed_graph(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    workflow_thread_id = "test-workflow-thread"

    evidence = RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=0,
        page_number=2,
        text="Duplicate payments require verification.",
        source_filename="payment-policy.pdf",
        vector_score=0.91,
        reranker_score=0.97,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    fake_checkpointer = object()

    @asynccontextmanager
    async def fake_open_incident_checkpointer() -> AsyncIterator[object]:
        yield fake_checkpointer

    class FakeGraph:
        async def ainvoke(
            self,
            state,
            *,
            config,
            context,
        ):
            assert state == {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": workflow_thread_id,
            }

            assert config == {
                "configurable": {
                    "thread_id": workflow_thread_id,
                }
            }

            assert context.session is session

            return {
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
                "evidence": [evidence],
                "analysis": ("The evidence supports a duplicate payment [SOURCE 1]."),
                "recommended_action": ("Verify transaction IDs [SOURCE 1]."),
            }

    def fake_build_incident_investigation_graph(
        *,
        checkpointer,
    ):
        assert checkpointer is fake_checkpointer

        return FakeGraph()

    monkeypatch.setattr(
        investigation_module,
        "open_incident_checkpointer",
        fake_open_incident_checkpointer,
    )

    monkeypatch.setattr(
        investigation_module,
        "build_incident_investigation_graph",
        fake_build_incident_investigation_graph,
    )

    result = asyncio.run(
        investigation_module.investigate_incident(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            workflow_thread_id=workflow_thread_id,
        )
    )

    assert result.incident_id == incident_id

    assert result.workflow_thread_id == workflow_thread_id

    assert result.category == IncidentCategory.PAYMENT
    assert result.priority == IncidentPriority.HIGH

    assert result.classification_confidence == 0.98

    assert len(result.evidence) == 1
