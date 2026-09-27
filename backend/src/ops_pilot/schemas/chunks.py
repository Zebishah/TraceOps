import uuid

from pydantic import BaseModel


class DocumentChunk(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    document_id: uuid.UUID

    chunk_index: int
    page_number: int

    text: str

    source_filename: str
    document_checksum: str
