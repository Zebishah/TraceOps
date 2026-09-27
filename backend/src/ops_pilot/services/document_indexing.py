import logging
import uuid

from qdrant_client import models
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.ai.embeddings import embed_texts
from ops_pilot.core.config import get_settings
from ops_pilot.core.exceptions import DocumentProcessingError
from ops_pilot.services.document_chunking import prepare_document_chunks
from ops_pilot.vectorstore.qdrant import (
    ensure_document_collection,
    get_qdrant_client,
)

logger = logging.getLogger(__name__)


async def index_document(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
) -> int:
    chunks = await prepare_document_chunks(
        session=session,
        organization_id=organization_id,
        document_id=document_id,
    )

    try:
        await ensure_document_collection()

        vectors = await embed_texts([chunk.text for chunk in chunks])

        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding count does not match chunk count")

        settings = get_settings()
        client = get_qdrant_client()

        # Remove old vectors for this document first.
        # This prevents stale/duplicate chunks after re-indexing.
        await client.delete(
            collection_name=settings.qdrant_collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="organization_id",
                            match=models.MatchValue(
                                value=str(organization_id),
                            ),
                        ),
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(
                                value=str(document_id),
                            ),
                        ),
                    ]
                )
            ),
            wait=True,
        )

        points: list[models.PointStruct] = []

        for chunk, vector in zip(
            chunks,
            vectors,
            strict=True,
        ):
            points.append(
                models.PointStruct(
                    id=str(chunk.id),
                    vector=vector,
                    payload={
                        "organization_id": str(chunk.organization_id),
                        "document_id": str(chunk.document_id),
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "text": chunk.text,
                        "source_filename": chunk.source_filename,
                        "document_checksum": (chunk.document_checksum),
                        "embedding_model": (settings.embedding_model),
                    },
                )
            )

        await client.upsert(
            collection_name=settings.qdrant_collection_name,
            points=points,
            wait=True,
        )

        return len(points)

    except DocumentProcessingError:
        raise

    except Exception as exc:
        logger.exception(
            "Document indexing failed",
            extra={
                "organization_id": str(organization_id),
                "document_id": str(document_id),
            },
        )

        raise DocumentProcessingError from exc
