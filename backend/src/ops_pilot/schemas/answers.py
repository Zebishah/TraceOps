import uuid

from pydantic import BaseModel, Field


class AnswerRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=2000,
    )


class Citation(BaseModel):
    source_number: int
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_filename: str
    page_number: int


class AnswerResponse(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
