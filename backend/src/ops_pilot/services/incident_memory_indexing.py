import uuid

from qdrant_client import models
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.ai.embeddings import embed_texts
from ops_pilot.core.config import get_settings
from ops_pilot.models.incident_memory import IncidentMemory
from ops_pilot.services.incident_memories import (
    get_incident_memory,
)
from ops_pilot.vectorstore.qdrant import (
    ensure_memory_collection,
    get_qdrant_client,
)


def build_memory_embedding_text(
    memory: IncidentMemory,
) -> str:
    return (
        f"Category: {memory.category}\n"
        f"Incident summary: {memory.summary}\n"
        f"Resolution: {memory.resolution}"
    )


async def index_incident_memory(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> int:
    memory = await get_incident_memory(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    if memory is None:
        raise RuntimeError(
            "Incident memory must exist before indexing",
        )

    text = build_memory_embedding_text(
        memory,
    )

    await session.rollback()

    await ensure_memory_collection()

    vectors = await embed_texts(
        [text],
    )

    if len(vectors) != 1:
        raise RuntimeError(
            "Expected exactly one memory embedding",
        )

    settings = get_settings()
    client = get_qdrant_client()

    await client.upsert(
        collection_name=settings.qdrant_memory_collection_name,
        points=[
            models.PointStruct(
                id=str(memory.id),
                vector=vectors[0],
                payload={
                    "organization_id": str(
                        memory.organization_id,
                    ),
                    "incident_id": str(
                        memory.incident_id,
                    ),
                    "subject_customer_id": (
                        str(memory.subject_customer_id)
                        if memory.subject_customer_id is not None
                        else None
                    ),
                    "category": memory.category,
                    "summary": memory.summary,
                    "resolution": memory.resolution,
                    "embedding_model": (settings.embedding_model),
                },
            )
        ],
        wait=True,
    )

    return 1
