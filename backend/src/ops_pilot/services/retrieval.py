import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import models

from ops_pilot.ai.embeddings import embed_query
from ops_pilot.ai.reranker import rerank_passages
from ops_pilot.core.config import get_settings
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.vectorstore.qdrant import get_qdrant_client


@dataclass
class RetrievalCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    text: str
    source_filename: str
    vector_score: float
    page_number: int


async def retrieve_document_chunks(
    *,
    organization_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[RetrievalResult]:
    settings = get_settings()

    query_vector = await embed_query(query)

    client = get_qdrant_client()

    response = await client.query_points(
        collection_name=settings.qdrant_collection_name,
        query=query_vector,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="organization_id",
                    match=models.MatchValue(
                        value=str(organization_id),
                    ),
                )
            ]
        ),
        limit=max(
            limit,
            settings.retrieval_candidate_limit,
        ),
        with_payload=True,
        with_vectors=False,
    )

    candidates: list[RetrievalCandidate] = []

    for point in response.points:
        payload: dict[str, Any] = point.payload or {}

        candidates.append(
            RetrievalCandidate(
                chunk_id=uuid.UUID(str(point.id)),
                document_id=uuid.UUID(str(payload["document_id"])),
                chunk_index=int(payload["chunk_index"]),
                text=str(payload["text"]),
                source_filename=str(payload["source_filename"]),
                vector_score=float(point.score),
                page_number=int(payload["page_number"]),
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
        RetrievalResult(
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            chunk_index=candidate.chunk_index,
            page_number=candidate.page_number,
            text=candidate.text,
            source_filename=candidate.source_filename,
            vector_score=candidate.vector_score,
            reranker_score=reranker_score,
        )
        for candidate, reranker_score in ranked[:limit]
    ]
