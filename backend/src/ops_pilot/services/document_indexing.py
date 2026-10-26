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

SCROLL_PAGE_SIZE = 256


def _document_filter(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
) -> models.Filter:
    return models.Filter(
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
        collection = settings.qdrant_collection_name

        document_filter = _document_filter(
            organization_id=organization_id,
            document_id=document_id,
        )

        # Snapshot the IDs belonging to the document.
        # Do not delete anything yet.
        previous_point_ids: set[str] = set()
        offset: models.ExtendedPointId | None = None

        while True:
            records, next_offset = await client.scroll(
                collection_name=collection,
                scroll_filter=document_filter,
                limit=SCROLL_PAGE_SIZE,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )

            for record in records:
                previous_point_ids.add(str(record.id))

            if next_offset is None:
                break

            if next_offset == offset:
                raise RuntimeError("Qdrant scroll offset did not advance")

            offset = next_offset

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
                        "source_filename": (chunk.source_filename),
                        "document_checksum": (chunk.document_checksum),
                        "embedding_model": (settings.embedding_model),
                    },
                )
            )

        # Upload first. If this fails, the old points
        # have not been deliberately deleted.
        if points:
            await client.upsert(
                collection_name=collection,
                points=points,
                wait=True,
            )

        current_ids: set[str] = {str(point.id) for point in points}

        stale_ids = previous_point_ids - current_ids

        # Delete only obsolete IDs from the snapshot.
        # Never delete by document filter after upsert:
        # that could also delete the newly uploaded points.

        if stale_ids:
            await client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(
                    points=list(stale_ids),
                ),
                wait=True,
            )

        logger.info(
            "document_indexed",
            extra={
                "organization_id": str(organization_id),
                "document_id": str(document_id),
                "point_count": len(points),
                "stale_points_removed": len(stale_ids),
            },
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
