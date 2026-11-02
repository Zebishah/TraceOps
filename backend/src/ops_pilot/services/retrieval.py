import logging
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qdrant_client import models
from qdrant_client.http.models import QueryResponse
from sqlalchemy import select

from ops_pilot.ai.embeddings import embed_query
from ops_pilot.ai.reranker import rerank_passages
from ops_pilot.core.config import get_settings
from ops_pilot.db.session import async_session_factory
from ops_pilot.integrations.observability import (
    observe_external_call,
)
from ops_pilot.models.document import Document
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.vectorstore.qdrant import get_qdrant_client

logger = logging.getLogger(__name__)


@dataclass
class RetrievalCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    text: str
    source_filename: str
    vector_score: float
    page_number: int
    index_generation: uuid.UUID | None = None


async def filter_active_document_generations(
    *,
    organization_id: uuid.UUID,
    candidates: list[RetrievalCandidate],
) -> list[RetrievalCandidate]:
    """Return only chunks from each document's active DB generation."""

    if not candidates:
        return []

    document_ids = {candidate.document_id for candidate in candidates}

    async with async_session_factory() as session:
        result = await session.execute(
            select(
                Document.id,
                Document.active_index_generation,
            ).where(
                Document.organization_id == organization_id,
                Document.id.in_(document_ids),
            )
        )

        active_generations = {document_id: generation for document_id, generation in result.all()}

    verified: list[RetrievalCandidate] = []

    for candidate in candidates:
        # A deleted document must never be returned.
        if candidate.document_id not in active_generations:
            continue

        active_generation = active_generations[candidate.document_id]

        # Legacy documents have no generation assigned.
        # They may only return legacy, unversioned points.
        if active_generation is None:
            if candidate.index_generation is None:
                verified.append(candidate)
            continue

        # New documents may only return points belonging
        # to their currently published generation.
        if candidate.index_generation == active_generation:
            verified.append(candidate)

    return verified


# A query over every document generation can exceed Qdrant filter limits.
# Each page is queried independently, and the best candidates are merged.
GENERATION_PAGE_SIZE = 100


def _generation_filter(
    *,
    organization_id: uuid.UUID,
    active_generations: Sequence[uuid.UUID],
    legacy_document_ids: Sequence[uuid.UUID],
) -> models.Filter:
    eligible: list[models.Condition] = []

    if active_generations:
        eligible.append(
            models.FieldCondition(
                key="index_generation",
                match=models.MatchAny(any=[str(value) for value in active_generations]),
            )
        )

    if legacy_document_ids:
        eligible.append(
            models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchAny(any=[str(value) for value in legacy_document_ids]),
                    ),
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="index_generation")),
                ]
            )
        )

    if not eligible:
        raise ValueError("Empty eligible document generation filter")

    return models.Filter(
        must=[
            models.FieldCondition(
                key="organization_id",
                match=models.MatchValue(value=str(organization_id)),
            ),
            models.Filter(should=eligible),
        ]
    )


async def _eligible_generation_pages(
    *,
    organization_id: uuid.UUID,
) -> list[tuple[list[uuid.UUID], list[uuid.UUID]]]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(Document.id, Document.active_index_generation).where(
                    Document.organization_id == organization_id,
                )
            )
        ).all()

    active = [generation for _document_id, generation in rows if generation is not None]
    legacy = [document_id for document_id, generation in rows if generation is None]

    pages: list[tuple[list[uuid.UUID], list[uuid.UUID]]] = []
    for offset in range(0, len(active), GENERATION_PAGE_SIZE):
        pages.append((active[offset : offset + GENERATION_PAGE_SIZE], []))
    for offset in range(0, len(legacy), GENERATION_PAGE_SIZE):
        pages.append(([], legacy[offset : offset + GENERATION_PAGE_SIZE]))
    return pages


async def retrieve_document_chunks(
    *,
    organization_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[RetrievalResult]:
    settings = get_settings()
    pages = await _eligible_generation_pages(
        organization_id=organization_id,
    )
    if not pages:
        return []
    query_vector = await embed_query(query)
    client = get_qdrant_client()
    candidate_limit = max(limit, settings.retrieval_candidate_limit)
    candidates_by_chunk: dict[uuid.UUID, RetrievalCandidate] = {}

    for active_generations, legacy_document_ids in pages:
        query_filter = _generation_filter(
            organization_id=organization_id,
            active_generations=active_generations,
            legacy_document_ids=legacy_document_ids,
        )

        async def run_qdrant_query(
            query_filter: models.Filter = query_filter,
        ) -> QueryResponse:
            return await client.query_points(
                collection_name=settings.qdrant_collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=candidate_limit,
                with_payload=True,
                with_vectors=False,
            )

        response = await observe_external_call(
            provider="qdrant",
            operation="document_vector_search",
            metadata={"organization_id": str(organization_id)},
            call=run_qdrant_query,
        )

        for point in response.points:
            candidate = parse_retrieval_candidate(
                point=point,
                organization_id=organization_id,
            )
            if candidate is not None:
                previous = candidates_by_chunk.get(candidate.chunk_id)
                if previous is None or candidate.vector_score > previous.vector_score:
                    candidates_by_chunk[candidate.chunk_id] = candidate

    candidates = sorted(
        candidates_by_chunk.values(),
        key=lambda candidate: candidate.vector_score,
        reverse=True,
    )[:candidate_limit]

    # Verify Qdrant results against PostgreSQL before
    # allowing them into the reranker or API response.
    candidates = await filter_active_document_generations(
        organization_id=organization_id,
        candidates=candidates,
    )

    if not candidates:
        return []

    try:
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

    except Exception:
        logger.warning(
            "retrieval_reranker_fallback",
            extra={
                "provider": "voyage",
                "operation": "rerank",
                "organization_id": str(organization_id),
                "candidate_count": len(candidates),
            },
            exc_info=True,
        )

        ranked = [
            (
                candidate,
                candidate.vector_score,
            )
            for candidate in sorted(
                candidates,
                key=lambda item: item.vector_score,
                reverse=True,
            )
        ]

    return [
        RetrievalResult(
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            chunk_index=candidate.chunk_index,
            page_number=candidate.page_number,
            text=candidate.text,
            source_filename=(candidate.source_filename),
            vector_score=(candidate.vector_score),
            reranker_score=reranker_score,
        )
        for candidate, reranker_score in ranked[:limit]
    ]


def parse_retrieval_candidate(
    *,
    point: Any,
    organization_id: uuid.UUID,
) -> RetrievalCandidate | None:
    """Validate one Qdrant point; never trust payload metadata."""

    try:
        payload = point.payload

        if not isinstance(payload, dict):
            raise ValueError("Invalid payload")

        if payload.get("organization_id") != str(organization_id):
            raise ValueError("Organization mismatch")

        chunk_id = uuid.UUID(str(point.id))
        document_id = uuid.UUID(str(payload["document_id"]))
        raw_generation = payload.get("index_generation")

        if raw_generation is None:
            index_generation = None
        elif isinstance(raw_generation, str):
            index_generation = uuid.UUID(raw_generation)
        else:
            raise ValueError("Invalid index generation")

        chunk_index = payload["chunk_index"]
        page_number = payload["page_number"]

        if (
            type(chunk_index) is not int
            or chunk_index < 0
            or type(page_number) is not int
            or page_number < 1
        ):
            raise ValueError("Invalid chunk or page index")

        text = payload["text"]
        source_filename = payload["source_filename"]

        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(source_filename, str)
            or not source_filename.strip()
        ):
            raise ValueError("Invalid text metadata")

        score = float(point.score)

        if not math.isfinite(score):
            raise ValueError("Invalid vector score")

        return RetrievalCandidate(
            chunk_id=chunk_id,
            document_id=document_id,
            chunk_index=chunk_index,
            page_number=page_number,
            text=text,
            source_filename=source_filename,
            vector_score=score,
            index_generation=index_generation,
        )

    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        logger.warning(
            "retrieval_invalid_qdrant_point_skipped",
            extra={
                "organization_id": str(organization_id),
                "point_id": str(getattr(point, "id", "unknown"))[:80],
            },
        )
        return None
