from qdrant_client import AsyncQdrantClient, models

from ops_pilot.core.config import get_settings


def get_qdrant_client() -> AsyncQdrantClient:
    settings = get_settings()

    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
    )


async def ensure_document_collection() -> None:
    settings = get_settings()
    client = get_qdrant_client()

    exists = await client.collection_exists(
        collection_name=settings.qdrant_collection_name,
    )

    if exists:
        return

    await client.create_collection(
        collection_name=settings.qdrant_collection_name,
        vectors_config=models.VectorParams(
            size=settings.embedding_dimension,
            distance=models.Distance.COSINE,
        ),
    )

    await client.create_payload_index(
        collection_name=settings.qdrant_collection_name,
        field_name="organization_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    await client.create_payload_index(
        collection_name=settings.qdrant_collection_name,
        field_name="document_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
