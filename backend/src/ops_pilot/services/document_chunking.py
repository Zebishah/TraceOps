import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    DocumentProcessingError,
)
from ops_pilot.ingestion.chunking import (
    create_document_chunks,
)
from ops_pilot.ingestion.extractors import ExtractedDocument
from ops_pilot.schemas.chunks import DocumentChunk
from ops_pilot.services.document_processing import (
    get_document,
)
from ops_pilot.storage.s3 import S3Storage


async def prepare_document_chunks(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
) -> list[DocumentChunk]:
    document = await get_document(
        session=session,
        organization_id=organization_id,
        document_id=document_id,
    )

    if document.extracted_text_key is None:
        raise DocumentProcessingError

    # Copy DB values before ending the transaction.
    extracted_text_key = document.extracted_text_key
    document_org_id = document.organization_id
    current_document_id = document.id
    source_filename = document.original_filename
    document_checksum = document.checksum_sha256

    # Important:
    # We no longer need PostgreSQL during S3/chunking/embedding work.
    await session.rollback()

    storage = S3Storage()

    try:
        extracted_bytes = await storage.download_file(
            key=extracted_text_key,
        )

        extracted = ExtractedDocument.model_validate_json(extracted_bytes)

        chunks = create_document_chunks(
            pages=extracted.pages,
            organization_id=document_org_id,
            document_id=current_document_id,
            source_filename=source_filename,
            document_checksum=document_checksum,
        )

        if not chunks:
            raise ValueError("Document produced no chunks")

        return chunks

    except DocumentProcessingError:
        raise

    except Exception as exc:
        raise DocumentProcessingError from exc
