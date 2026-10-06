import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IncidentMemoryCreate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    summary: str = Field(
        min_length=1,
        max_length=2000,
    )

    resolution: str = Field(
        min_length=1,
        max_length=2000,
    )


class IncidentMemoryResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: uuid.UUID
    organization_id: uuid.UUID
    incident_id: uuid.UUID
    subject_customer_id: uuid.UUID | None

    category: str
    summary: str
    resolution: str

    created_at: datetime
    updated_at: datetime


class IncidentMemoryRetrievalResult(BaseModel):
    memory_id: uuid.UUID
    incident_id: uuid.UUID
    subject_customer_id: uuid.UUID | None

    category: str
    summary: str
    resolution: str

    vector_score: float
