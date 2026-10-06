import uuid
from typing import Any

from qdrant_client import models

from ops_pilot.ai.embeddings import embed_query
from ops_pilot.core.config import get_settings
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryRetrievalResult,
)
from ops_pilot.vectorstore.qdrant import (
    ensure_memory_collection,
    get_qdrant_client,
)


def build_incident_memory_query(
    *,
    title: str,
    description: str,
    category: str,
) -> str:
    return f"Category: {category}\nIncident title: {title}\nIncident description: {description}"


async def retrieve_similar_incident_memories(
    *,
    organization_id: uuid.UUID,
    current_incident_id: uuid.UUID,
    title: str,
    description: str,
    category: str,
    limit: int = 3,
) -> list[IncidentMemoryRetrievalResult]:
    query = build_incident_memory_query(
        title=title,
        description=description,
        category=category,
    )

    query_vector = await embed_query(
        query,
    )

    await ensure_memory_collection()

    settings = get_settings()
    client = get_qdrant_client()

    response = await client.query_points(
        collection_name=settings.qdrant_memory_collection_name,
        query=query_vector,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="organization_id",
                    match=models.MatchValue(
                        value=str(organization_id),
                    ),
                ),
            ],
            must_not=[
                models.FieldCondition(
                    key="incident_id",
                    match=models.MatchValue(
                        value=str(current_incident_id),
                    ),
                ),
            ],
        ),
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )

    memories: list[IncidentMemoryRetrievalResult] = []

    for point in response.points:
        payload: dict[str, Any] = point.payload or {}

        memories.append(
            IncidentMemoryRetrievalResult(
                memory_id=uuid.UUID(
                    str(point.id),
                ),
                incident_id=uuid.UUID(
                    str(payload["incident_id"]),
                ),
                subject_customer_id=(
                    uuid.UUID(
                        str(payload["subject_customer_id"]),
                    )
                    if payload.get("subject_customer_id")
                    else None
                ),
                category=str(
                    payload["category"],
                ),
                summary=str(
                    payload["summary"],
                ),
                resolution=str(
                    payload["resolution"],
                ),
                vector_score=float(
                    point.score,
                ),
            )
        )

    return memories
