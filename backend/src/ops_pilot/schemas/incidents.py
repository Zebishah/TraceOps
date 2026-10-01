import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.tools.schemas import ToolExecutionResult


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
    )
    subject_customer_id: uuid.UUID | None = None
    title: str = Field(
        min_length=1,
        max_length=200,
    )

    description: str = Field(
        min_length=1,
    )


class IncidentResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: uuid.UUID
    organization_id: uuid.UUID
    created_by_user_id: uuid.UUID
    subject_customer_id: uuid.UUID | None
    title: str
    description: str

    status: IncidentStatus
    category: str | None
    priority: IncidentPriority | None

    created_at: datetime
    updated_at: datetime


class IncidentClassificationResponse(BaseModel):
    incident_id: uuid.UUID
    status: IncidentStatus
    category: IncidentCategory
    priority: IncidentPriority
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )


class IncidentEvidenceResponse(BaseModel):
    incident_id: uuid.UUID
    query: str
    evidence: list[RetrievalResult]


class IncidentInvestigationResponse(BaseModel):
    organization_id: uuid.UUID
    incident_id: uuid.UUID

    title: str
    description: str

    status: IncidentStatus
    category: IncidentCategory
    priority: IncidentPriority
    classification_confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    retrieval_query: str
    evidence: list[RetrievalResult]

    tool_results: list[ToolExecutionResult] = Field(
        default_factory=list,
    )

    needs_more_information: bool = False
    clarification_question: str | None = None

    analysis: str | None = None
    recommended_action: str | None = None
