import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.retrieval as retrieval_module
from ops_pilot.schemas.retrieval import RetrievalResult


@pytest.mark.asyncio
async def test_retrieval_result_schema() -> None:
    result = RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=3,
        page_number=2,
        text="Refunds are allowed within 30 days.",
        source_filename="refund-policy.pdf",
        vector_score=0.82,
        reranker_score=4.25,
    )

    assert result.chunk_index == 3
    assert result.page_number == 2
    assert result.vector_score == 0.82
    assert result.reranker_score == 4.25


@pytest.mark.asyncio
async def test_retrieval_falls_back_to_vector_scores_when_reranker_fails(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()

    first_chunk_id = uuid.uuid4()
    second_chunk_id = uuid.uuid4()

    first_document_id = uuid.uuid4()
    second_document_id = uuid.uuid4()

    points = [
        SimpleNamespace(
            id=first_chunk_id,
            score=0.91,
            payload={
                "document_id": str(first_document_id),
                "chunk_index": 0,
                "text": "Highest vector match",
                "source_filename": "a.pdf",
                "page_number": 1,
            },
        ),
        SimpleNamespace(
            id=second_chunk_id,
            score=0.72,
            payload={
                "document_id": str(second_document_id),
                "chunk_index": 1,
                "text": "Lower vector match",
                "source_filename": "b.pdf",
                "page_number": 2,
            },
        ),
    ]

    fake_qdrant = SimpleNamespace(
        query_points=AsyncMock(
            return_value=SimpleNamespace(
                points=points,
            )
        )
    )

    monkeypatch.setattr(
        retrieval_module,
        "get_settings",
        lambda: SimpleNamespace(
            qdrant_collection_name="test",
            retrieval_candidate_limit=12,
        ),
    )

    monkeypatch.setattr(
        retrieval_module,
        "embed_query",
        AsyncMock(
            return_value=[
                0.1,
                0.2,
            ]
        ),
    )

    monkeypatch.setattr(
        retrieval_module,
        "get_qdrant_client",
        lambda: fake_qdrant,
    )

    monkeypatch.setattr(
        retrieval_module,
        "rerank_passages",
        AsyncMock(side_effect=RuntimeError("Voyage unavailable")),
    )

    results = await retrieval_module.retrieve_document_chunks(
        organization_id=organization_id,
        query="refund problem",
        limit=2,
    )

    assert len(results) == 2

    assert results[0].chunk_id == first_chunk_id

    assert results[1].chunk_id == second_chunk_id

    assert results[0].reranker_score == 0.91

    assert results[1].reranker_score == 0.72
