from dataclasses import dataclass
from typing import Any

from ops_pilot.ai.embeddings import embed_query
from ops_pilot.ai.reranker import rerank_passages
from ops_pilot.core.config import get_settings
from ops_pilot.schemas.project_knowledge import (
    ProjectKnowledgeResult,
)
from ops_pilot.vectorstore.qdrant import (
    get_active_project_knowledge_collection_name,
    get_qdrant_client,
)


@dataclass
class ProjectKnowledgeCandidate:
    source: str
    section: str
    text: str
    vector_score: float


async def search_project_knowledge(
    *,
    query: str,
    limit: int = 5,
) -> list[ProjectKnowledgeResult]:
    settings = get_settings()

    query_vector = await embed_query(query)

    client = get_qdrant_client()
    active_collection = await get_active_project_knowledge_collection_name()
    response = await client.query_points(
        collection_name=active_collection,
        query=query_vector,
        limit=max(
            limit,
            settings.retrieval_candidate_limit,
        ),
        with_payload=True,
        with_vectors=False,
    )

    candidates: list[ProjectKnowledgeCandidate] = []

    for point in response.points:
        payload: dict[str, Any] = point.payload or {}

        candidates.append(
            ProjectKnowledgeCandidate(
                source=str(payload["source"]),
                section=str(payload["section"]),
                text=str(payload["text"]),
                vector_score=float(point.score),
            )
        )

    if not candidates:
        return []

    reranker_scores = await rerank_passages(
        query=query,
        passages=[candidate.text for candidate in candidates],
    )

    if len(reranker_scores) != len(candidates):
        raise RuntimeError("Reranker score count does not match candidate count")

    ranked = sorted(
        zip(
            candidates,
            reranker_scores,
            strict=True,
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    return [
        ProjectKnowledgeResult(
            source=candidate.source,
            section=candidate.section,
            text=candidate.text,
            vector_score=candidate.vector_score,
            reranker_score=reranker_score,
        )
        for candidate, reranker_score in ranked[:limit]
    ]
