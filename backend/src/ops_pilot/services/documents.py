"""Document uploads with bounded reads and content validation."""

import hashlib
import re
import unicodedata
import uuid
from pathlib import Path

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
MAX_FILENAME_LENGTH = 180

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
}


def normalize_document_filename(filename: str | None) -> str:
    """Turn an untrusted filename into a safe display filename."""

    value = unicodedata.normalize("NFKC", filename or "document")

    # Handle both Windows and POSIX path separators.
    value = value.replace("\\", "/").split("/")[-1]

    # Remove control characters and unsupported characters.
    value = "".join(character for character in value if unicodedata.category(character)[0] != "C")

    value = re.sub(r"[^a-zA-Z0-9._ -]", "_", value)
    value = value.strip(" ._-")

    if not value or value in {".", ".."}:
        return "document"

    # Keep the extension when truncating long filenames.
    extension = Path(value).suffix[:20]
    if extension and len(value) > MAX_FILENAME_LENGTH:
        stem = value[: -len(extension)]
        value = stem[: MAX_FILENAME_LENGTH - len(extension)] + extension

    return value[:MAX_FILENAME_LENGTH] or "document"


def validate_document_signature(
    *,
    mime_type: str,
    sample: bytes,
) -> None:
    """Check actual content rather than trusting the MIME header."""

    if mime_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedDocumentTypeError

    if not sample:
        raise UnsupportedDocumentTypeError

    if mime_type == "application/pdf":
        # A genuine PDF is expected to begin with its header.
        if not sample.startswith(b"%PDF-"):
            raise UnsupportedDocumentTypeError
        return

    # Text and Markdown must contain valid UTF-8 text.
    # A binary document must not masquerade as plain text.
    if b"\x00" in sample:
        raise UnsupportedDocumentTypeError


async def create_document(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    file: UploadFile,
) -> Document:
    mime_type = file.content_type or ""

    if mime_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedDocumentTypeError

    filename = normalize_document_filename(file.filename)
    document_id = uuid.uuid4()

    storage_key = f"organizations/{organization_id}/documents/{document_id}/{filename}"

    checksum = hashlib.sha256()
    size_bytes = 0

    # Check a small prefix before reading the whole upload.
    sample = await file.read(4096)
    validate_document_signature(
        mime_type=mime_type,
        sample=sample,
    )

    await file.seek(0)

    while True:
        chunk = await file.read(1024 * 1024)

        if not chunk:
            break

        size_bytes += len(chunk)

        if size_bytes > MAX_DOCUMENT_SIZE:
            raise DocumentTooLargeError

        checksum.update(chunk)

    # Check full UTF-8 validity for text documents, not just
    # the initial sample. Read at most the already-validated
    # 10 MB from the spooled upload.
    if mime_type in {"text/plain", "text/markdown"}:
        await file.seek(0)

        try:
            (await file.read(MAX_DOCUMENT_SIZE + 1)).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedDocumentTypeError from exc

    await file.seek(0)

    document = Document(
        id=document_id,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
        original_filename=filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size_bytes,
        checksum_sha256=checksum.hexdigest(),
    )

    storage = S3Storage()
    upload_started = False

    try:
        upload_started = True

        await storage.upload_file(
            file=file.file,
            key=storage_key,
            content_type=mime_type,
        )

        session.add(document)

        await session.commit()
        await session.refresh(document)

        return document

    except Exception as exc:
        await session.rollback()

        # S3 upload failures can leave a partial object.
        # Attempt cleanup even if upload_file raised.
        if upload_started:
            try:
                await storage.delete_file(key=storage_key)
            except Exception:
                pass

        raise DocumentUploadError from exc
