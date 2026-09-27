import uuid

from pydantic import BaseModel, Field


class RetrievalRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=2000,
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
    )


class RetrievalResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID

    chunk_index: int
    page_number: int

    text: str
    source_filename: str

    vector_score: float
    reranker_score: float


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievalResult]
