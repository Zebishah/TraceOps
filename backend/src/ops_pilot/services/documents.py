import hashlib
import uuid

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    DocumentTooLargeError,
    DocumentUploadError,
    UnsupportedDocumentTypeError,
)
from ops_pilot.models.document import Document
from ops_pilot.storage.s3 import S3Storage

MAX_DOCUMENT_SIZE = 10 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
}


async def create_document(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    file: UploadFile,
) -> Document:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedDocumentTypeError

    filename = file.filename or "document"

    document_id = uuid.uuid4()

    storage_key = f"organizations/{organization_id}/documents/{document_id}/{filename}"

    checksum = hashlib.sha256()
    size_bytes = 0

    while chunk := await file.read(1024 * 1024):
        size_bytes += len(chunk)

        if size_bytes > MAX_DOCUMENT_SIZE:
            raise DocumentTooLargeError

        checksum.update(chunk)

    checksum_sha256 = checksum.hexdigest()

    await file.seek(0)

    document = Document(
        id=document_id,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
        original_filename=filename,
        storage_key=storage_key,
        mime_type=file.content_type,
        size_bytes=size_bytes,
        checksum_sha256=checksum_sha256,
    )

    storage = S3Storage()

    uploaded_to_s3 = False

    try:
        await storage.upload_file(
            file=file.file,
            key=storage_key,
            content_type=file.content_type,
        )

        uploaded_to_s3 = True

        session.add(document)

        await session.commit()
        await session.refresh(document)

        return document

    except Exception as exc:
        await session.rollback()

        if uploaded_to_s3:
            try:
                await storage.delete_file(
                    key=storage_key,
                )
            except Exception:
                pass

        raise DocumentUploadError from exc
