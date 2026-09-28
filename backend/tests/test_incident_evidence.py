import asyncio
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.incident_evidence as evidence_module
from ops_pilot.schemas.retrieval import RetrievalResult


def test_retrieve_incident_evidence_uses_existing_retrieval(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    expected_organization_id = organization_id

    incident = SimpleNamespace(
        id=incident_id,
        title="Customer charged twice",
        description="Customer was charged twice for one order.",
        category="payment",
    )

    expected_result = RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=3,
        page_number=2,
        text="Duplicate charges must be refunded after verification.",
        source_filename="refund-policy.pdf",
        vector_score=0.82,
        reranker_score=0.94,
    )

    async def fake_get_incident(
        *,
        session,
        organization_id,
        incident_id,
    ):
        return incident

    async def fake_retrieve_document_chunks(
        *,
        organization_id,
        query,
        limit,
    ):
        assert organization_id == expected_organization_id
        assert "Customer charged twice" in query
        assert "payment" in query
        assert limit == 5

        return [expected_result]

    monkeypatch.setattr(
        evidence_module,
        "get_incident",
        fake_get_incident,
    )

    monkeypatch.setattr(
        evidence_module,
        "retrieve_document_chunks",
        fake_retrieve_document_chunks,
    )
    session_mock = AsyncMock(spec=AsyncSession)

    session = cast(
        AsyncSession,
        session_mock,
    )

    query, results = asyncio.run(
        evidence_module.retrieve_incident_evidence(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )
    )

    assert "Customer charged twice" in query
    assert "Incident category: payment" in query
    assert results == [expected_result]

    session_mock.rollback.assert_awaited_once()
