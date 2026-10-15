from pydantic import BaseModel, Field


class ProjectKnowledgeResult(BaseModel):
    source: str
    section: str
    text: str
    vector_score: float
    reranker_score: float


class ProjectKnowledgeSearchResponse(BaseModel):
    query: str
    results: list[ProjectKnowledgeResult]


class ProjectKnowledgeSearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=2000,
    )

    limit: int = Field(
        default=5,
        ge=1,
        le=10,
    )
