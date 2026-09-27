import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    DocumentNotFoundError,
    DocumentProcessingError,
)
from ops_pilot.ingestion.extractors import extract_document_text
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
