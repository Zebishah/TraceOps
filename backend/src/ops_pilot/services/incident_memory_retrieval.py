import uuid

from qdrant_client import models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.ai.embeddings import (
    embed_query,
)
from ops_pilot.core.config import (
    get_settings,
)
from ops_pilot.models.incident_memory import (
    IncidentMemory,
)
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
    session: AsyncSession,
    organization_id: uuid.UUID,
    current_incident_id: uuid.UUID,
    title: str,
    description: str,
    category: str,
    limit: int = 3,
) -> list[IncidentMemoryRetrievalResult]:
    if limit <= 0:
        return []

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
        collection_name=(settings.qdrant_memory_collection_name),
        query=query_vector,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="organization_id",
                    match=models.MatchValue(
                        value=str(
                            organization_id,
                        ),
                    ),
                ),
            ],
            must_not=[
                models.FieldCondition(
                    key="incident_id",
                    match=models.MatchValue(
                        value=str(
                            current_incident_id,
                        ),
                    ),
                ),
            ],
        ),
        limit=limit,
        with_payload=False,
        with_vectors=False,
    )

    scored_memory_ids: list[tuple[uuid.UUID, float]] = []

    for point in response.points:
        try:
            memory_id = uuid.UUID(
                str(point.id),
            )
        except ValueError:
            # Ignore malformed Qdrant records.
            continue

        scored_memory_ids.append(
            (
                memory_id,
                float(point.score),
            )
        )

    if not scored_memory_ids:
        return []

    memory_ids = [memory_id for memory_id, _ in scored_memory_ids]

    result = await session.execute(
        select(IncidentMemory).where(
            IncidentMemory.id.in_(
                memory_ids,
            ),
            IncidentMemory.organization_id == organization_id,
            IncidentMemory.incident_id != current_incident_id,
        )
    )

    db_memories = list(result.scalars().all())

    memories_by_id = {memory.id: memory for memory in db_memories}

    retrieved: list[IncidentMemoryRetrievalResult] = []

    for memory_id, score in scored_memory_ids:
        memory = memories_by_id.get(
            memory_id,
        )

        # Qdrant may contain an old/stale point.
        # If PostgreSQL no longer has it,
        # never expose it to the AI.
        if memory is None:
            continue

        retrieved.append(
            IncidentMemoryRetrievalResult(
                memory_id=memory.id,
                incident_id=memory.incident_id,
                subject_customer_id=(memory.subject_customer_id),
                category=memory.category,
                summary=memory.summary,
                resolution=(
                    "Historical context only. This retrieved memory "
                    "does not independently verify execution by an "
                    "external payment provider. Historical resolution: "
                    f"{memory.resolution}"
                ),
                vector_score=score,
            )
        )

    # We copied everything into Pydantic values.
    # Do not keep a DB transaction open while
    # the graph continues to external services.
    await session.rollback()

    return retrieved
