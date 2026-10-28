import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.retrieval as retrieval


def test_generation_query_includes_tenant_and_legacy_constraints():
    org = uuid.uuid4()
    gen = uuid.uuid4()
    legacy = uuid.uuid4()
    filt = retrieval._generation_filter(
        organization_id=org,
        active_generations=[gen],
        legacy_document_ids=[legacy],
    )
    payload = filt.model_dump(exclude_none=True, mode="json")
    assert str(org) in str(payload)
    assert str(gen) in str(payload)
    assert str(legacy) in str(payload)
    assert "index_generation" in str(payload)
    assert "is_empty" in str(payload)


@pytest.mark.asyncio
async def test_empty_eligible_documents_do_not_query_qdrant(monkeypatch):
    monkeypatch.setattr(retrieval, "_eligible_generation_pages", AsyncMock(return_value=[]))
    monkeypatch.setattr(retrieval, "embed_query", AsyncMock(return_value=[0.2]))
    qdrant = SimpleNamespace(query_points=AsyncMock())
    monkeypatch.setattr(retrieval, "get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr(
        retrieval,
        "get_settings",
        lambda: SimpleNamespace(qdrant_collection_name="test", retrieval_candidate_limit=12),
    )
    assert (
        await retrieval.retrieve_document_chunks(organization_id=uuid.uuid4(), query="anything")
        == []
    )
    qdrant.query_points.assert_not_awaited()
