import uuid
from datetime import datetime

from pydantic import BaseModel

from ops_pilot.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    uploaded_by_user_id: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    status: DocumentStatus
    failure_reason: str | None
    created_at: datetime


class DocumentIndexResponse(BaseModel):
    document_id: uuid.UUID
    indexed_chunks: int
