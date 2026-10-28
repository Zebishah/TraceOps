from functools import lru_cache

from qdrant_client import AsyncQdrantClient, models

from ops_pilot.core.config import get_settings


@lru_cache
def get_qdrant_client() -> AsyncQdrantClient:
    settings = get_settings()

    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
    )


async def close_qdrant_client() -> None:
    if get_qdrant_client.cache_info().currsize == 0:
        return

    client = get_qdrant_client()

    await client.close()

    get_qdrant_client.cache_clear()


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


async def ensure_memory_collection() -> None:
    settings = get_settings()
    client = get_qdrant_client()

    exists = await client.collection_exists(
        collection_name=settings.qdrant_memory_collection_name,
    )

    if exists:
        return

    await client.create_collection(
        collection_name=settings.qdrant_memory_collection_name,
        vectors_config=models.VectorParams(
            size=settings.embedding_dimension,
            distance=models.Distance.COSINE,
        ),
    )

    await client.create_payload_index(
        collection_name=settings.qdrant_memory_collection_name,
        field_name="organization_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    await client.create_payload_index(
        collection_name=settings.qdrant_memory_collection_name,
        field_name="incident_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    await client.create_payload_index(
        collection_name=settings.qdrant_memory_collection_name,
        field_name="subject_customer_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    await client.create_payload_index(
        collection_name=settings.qdrant_memory_collection_name,
        field_name="category",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )


async def ensure_project_knowledge_collection() -> None:
    settings = get_settings()
    client = get_qdrant_client()

    exists = await client.collection_exists(
        collection_name=(settings.qdrant_project_knowledge_collection_name),
    )

    if exists:
        return

    await client.create_collection(
        collection_name=(settings.qdrant_project_knowledge_collection_name),
        vectors_config=models.VectorParams(
            size=settings.embedding_dimension,
            distance=models.Distance.COSINE,
        ),
    )

    await client.create_payload_index(
        collection_name=(settings.qdrant_project_knowledge_collection_name),
        field_name="source",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    await client.create_payload_index(
        collection_name=(settings.qdrant_project_knowledge_collection_name),
        field_name="section",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )


async def get_active_project_knowledge_collection_name() -> str:
    """Resolve the active version, falling back to the legacy collection.

    The legacy name remains readable while the first versioned
    collection is prepared. Once published, readers use the alias.
    """
    settings = get_settings()
    client = get_qdrant_client()

    legacy_name = settings.qdrant_project_knowledge_collection_name
    active_alias = f"{legacy_name}__active"

    aliases = await client.get_aliases()

    if any(alias.alias_name == active_alias for alias in aliases.aliases):
        return active_alias

    return legacy_name
