from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ops_pilot.services import project_knowledge


@pytest.mark.anyio
async def test_search_project_knowledge_reranks_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_query_vector = [0.1, 0.2, 0.3]

    async def fake_embed_query(query: str) -> list[float]:
        assert query == "How does OpsPilot use LangGraph?"
        return fake_query_vector

    async def fake_rerank_passages(
        *,
        query: str,
        passages: list[str],
    ) -> list[float]:
        assert query == "How does OpsPilot use LangGraph?"
        assert passages == [
            "LangGraph controls the incident workflow.",
            "n8n handles business automation.",
            "Qdrant stores vector embeddings.",
        ]

        return [
            0.95,
            0.40,
            0.70,
        ]

    point_one = SimpleNamespace(
        payload={
            "source": "architecture.md",
            "section": "LangGraph",
            "text": "LangGraph controls the incident workflow.",
        },
        score=0.82,
    )

    point_two = SimpleNamespace(
        payload={
            "source": "automation-n8n.md",
            "section": "n8n",
            "text": "n8n handles business automation.",
        },
        score=0.78,
    )

    point_three = SimpleNamespace(
        payload={
            "source": "rag-and-retrieval.md",
            "section": "Qdrant",
            "text": "Qdrant stores vector embeddings.",
        },
        score=0.75,
    )

    fake_response = SimpleNamespace(
        points=[
            point_one,
            point_two,
            point_three,
        ],
    )

    fake_qdrant_client = AsyncMock()
    fake_qdrant_client.query_points.return_value = fake_response

    fake_settings = SimpleNamespace(
        qdrant_project_knowledge_collection_name=("ops_pilot_project_knowledge_v1"),
        retrieval_candidate_limit=12,
    )

    monkeypatch.setattr(
        project_knowledge,
        "embed_query",
        fake_embed_query,
    )

    monkeypatch.setattr(
        project_knowledge,
        "rerank_passages",
        fake_rerank_passages,
    )

    monkeypatch.setattr(
        project_knowledge,
        "get_qdrant_client",
        lambda: fake_qdrant_client,
    )

    monkeypatch.setattr(
        project_knowledge,
        "get_settings",
        lambda: fake_settings,
    )

    results = await project_knowledge.search_project_knowledge(
        query="How does OpsPilot use LangGraph?",
        limit=2,
    )

    fake_qdrant_client.query_points.assert_awaited_once_with(
        collection_name=("ops_pilot_project_knowledge_v1"),
        query=fake_query_vector,
        limit=12,
        with_payload=True,
        with_vectors=False,
    )

    assert len(results) == 2

    assert results[0].source == "architecture.md"
    assert results[0].section == "LangGraph"
    assert results[0].text == ("LangGraph controls the incident workflow.")
    assert results[0].vector_score == 0.82
    assert results[0].reranker_score == 0.95

    assert results[1].source == "rag-and-retrieval.md"
    assert results[1].section == "Qdrant"
    assert results[1].reranker_score == 0.70
