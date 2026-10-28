"""Conservative per-document vector cleanup; invoke only after backup/review.

Holds the document job row lock during Qdrant scroll/deletion so a new
indexing dispatch cannot publish concurrently. Never deletes the active
generation or a currently processing dispatch generation.
"""

import uuid

from qdrant_client import models
from sqlalchemy import select

from ops_pilot.core.config import get_settings
from ops_pilot.db.session import async_session_factory
from ops_pilot.models.background_job import BackgroundJob, BackgroundJobStatus, BackgroundJobType
from ops_pilot.models.document import Document
from ops_pilot.vectorstore.qdrant import get_qdrant_client


async def cleanup_document_generations(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    dry_run: bool = True,
) -> int:
    """Count/delete obsolete point IDs, never a document-wide filter delete."""
    async with async_session_factory() as session:
        async with session.begin():
            job = await session.scalar(
                select(BackgroundJob)
                .where(
                    BackgroundJob.organization_id == organization_id,
                    BackgroundJob.resource_id == document_id,
                    BackgroundJob.job_type == BackgroundJobType.DOCUMENT_PROCESSING,
                )
                .with_for_update()
            )
            if job is None:
                # No known dispatch fencing owner: fail closed.
                return 0
            document = await session.scalar(
                select(Document)
                .where(Document.id == document_id, Document.organization_id == organization_id)
                .with_for_update()
            )
            if document is None or document.active_index_generation is None:
                # Legacy/unpublished documents must not be cleaned.
                return 0

            keep = {str(document.active_index_generation)}
            if job.status in (BackgroundJobStatus.QUEUED, BackgroundJobStatus.PROCESSING):
                if job.dispatch_id is not None:
                    keep.add(str(job.dispatch_id))

            client = get_qdrant_client()
            collection = get_settings().qdrant_collection_name
            filt = models.Filter(
                must=[
                    models.FieldCondition(
                        key="organization_id",
                        match=models.MatchValue(value=str(organization_id)),
                    ),
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=str(document_id)),
                    ),
                ]
            )
            offset = None
            delete_ids = []
            while True:
                records, next_offset = await client.scroll(
                    collection_name=collection,
                    scroll_filter=filt,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in records:
                    payload = point.payload
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("organization_id") != str(organization_id) or payload.get(
                        "document_id"
                    ) != str(document_id):
                        continue
                    generation = payload.get("index_generation")
                    if generation is not None and not isinstance(generation, str):
                        continue
                    if generation not in keep:
                        delete_ids.append(point.id)
                if next_offset is None:
                    break
                if next_offset == offset:
                    raise RuntimeError("Qdrant scroll did not advance")
                offset = next_offset

            if not dry_run and delete_ids:
                # Serialize against indexing while holding the job lock.
                for index in range(0, len(delete_ids), 256):
                    await client.delete(
                        collection_name=collection,
                        points_selector=models.PointIdsList(points=delete_ids[index : index + 256]),
                        wait=True,
                    )
            return len(delete_ids)
