import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    DocumentNotFoundError,
    DocumentProcessingError,
)
from ops_pilot.db.session import async_session_factory
from ops_pilot.ingestion.extractors import extract_document_text
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
)
from ops_pilot.models.document import Document, DocumentStatus
from ops_pilot.storage.s3 import S3Storage


async def get_document(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
) -> Document:
    result = await session.execute(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == organization_id,
        )
    )

    document = result.scalar_one_or_none()

    if document is None:
        raise DocumentNotFoundError

    return document


async def process_document(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
) -> Document:
    document = await get_document(
        session=session,
        organization_id=organization_id,
        document_id=document_id,
    )

    storage = S3Storage()

    document.status = DocumentStatus.PROCESSING
    document.failure_reason = None
    document.extracted_text_key = None

    await session.commit()

    try:
        original_file = await storage.download_file(
            key=document.storage_key,
        )

        extracted = await extract_document_text(
            data=original_file,
            mime_type=document.mime_type,
        )

        if not extracted.pages:
            raise ValueError("No extractable text found in document")

        extracted_bytes = extracted.model_dump_json().encode("utf-8")

        extracted_text_key = (
            f"organizations/{organization_id}/documents/{document.id}/extracted.json"
        )

        await storage.upload_bytes(
            data=extracted_bytes,
            key=extracted_text_key,
            content_type="application/json",
        )

        document.extracted_text_key = extracted_text_key
        document.status = DocumentStatus.READY
        document.failure_reason = None

        await session.commit()
        await session.refresh(document)

        return document

    except Exception as exc:
        await session.rollback()

        document.status = DocumentStatus.FAILED
        document.failure_reason = str(exc)[:1000]

        await session.commit()

        raise DocumentProcessingError from exc


async def process_document_for_dispatch(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    job_id: uuid.UUID,
    dispatch_id: uuid.UUID,
) -> Document:
    """Process a document without allowing stale dispatch publication.

    Each execution uploads to a unique S3 key. Only the currently
    active job dispatch may publish that key to the document row.
    """

    async def require_active_job(session: AsyncSession) -> None:
        job = await session.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.organization_id == organization_id,
                BackgroundJob.resource_id == document_id,
            )
            .with_for_update()
        )

        if (
            job is None
            or job.dispatch_id != dispatch_id
            or job.status != BackgroundJobStatus.PROCESSING
        ):
            raise RuntimeError("Document processing dispatch is no longer active")

    # Read and validate the dispatch before external work.
    async with async_session_factory() as session:
        async with session.begin():
            await require_active_job(session)

            document = await get_document(
                session=session,
                organization_id=organization_id,
                document_id=document_id,
            )

            original_key = document.storage_key

    storage = S3Storage()

    try:
        original_file = await storage.download_file(
            key=original_key,
        )

        extracted = await extract_document_text(
            data=original_file,
            mime_type=document.mime_type,
        )

        if not extracted.pages:
            raise ValueError("No extractable text found in document")

        extracted_bytes = extracted.model_dump_json().encode("utf-8")

        # Never overwrite another dispatch's output.
        # The random execution ID also isolates duplicate workers
        # processing the same dispatch.
        extracted_text_key = (
            f"organizations/{organization_id}/documents/"
            f"{document_id}/extracted/"
            f"{dispatch_id}/{uuid.uuid4().hex}.json"
        )

        await storage.upload_bytes(
            data=extracted_bytes,
            key=extracted_text_key,
            content_type="application/json",
        )

        # Short transaction: lock job, recheck dispatch,
        # then publish only the current worker's output.
        async with async_session_factory() as session:
            async with session.begin():
                await require_active_job(session)

                result = await session.execute(
                    select(Document)
                    .where(
                        Document.id == document_id,
                        Document.organization_id == organization_id,
                    )
                    .with_for_update()
                )

                current = result.scalar_one_or_none()

                if current is None:
                    raise DocumentNotFoundError

                # Do not overwrite a result already published
                # by another execution of this same dispatch.
                if current.status == DocumentStatus.READY:
                    raise RuntimeError("Document result has already been published")

                current.extracted_text_key = extracted_text_key
                current.status = DocumentStatus.READY
                current.failure_reason = None

        async with async_session_factory() as session:
            return await get_document(
                session=session,
                organization_id=organization_id,
                document_id=document_id,
            )

    except Exception as exc:
        # A failed/stale worker must not overwrite a newer READY
        # document or a document belonging to a newer dispatch.
        async with async_session_factory() as session:
            async with session.begin():
                job = await session.scalar(
                    select(BackgroundJob)
                    .where(
                        BackgroundJob.id == job_id,
                        BackgroundJob.organization_id == organization_id,
                        BackgroundJob.resource_id == document_id,
                    )
                    .with_for_update()
                )

                if (
                    job is not None
                    and job.dispatch_id == dispatch_id
                    and job.status == BackgroundJobStatus.PROCESSING
                ):
                    current = await session.scalar(
                        select(Document)
                        .where(
                            Document.id == document_id,
                            Document.organization_id == organization_id,
                        )
                        .with_for_update()
                    )

                    if current is not None and current.status != DocumentStatus.READY:
                        current.status = DocumentStatus.FAILED
                        current.failure_reason = f"{type(exc).__name__}: {exc}"[:1000]

        raise DocumentProcessingError from exc
