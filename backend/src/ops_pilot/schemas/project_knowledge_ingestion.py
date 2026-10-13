import uuid

from pydantic import BaseModel


class ProjectKnowledgeChunk(BaseModel):
    id: uuid.UUID
    source: str
    section: str
    chunk_index: int
    text: str
