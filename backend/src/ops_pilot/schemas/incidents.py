import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryRetrievalResult,
)
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
    resolved_by_user_id: uuid.UUID | None = None
    resolution_reason: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IncidentAcknowledgmentResponse(BaseModel):
    incident_id: uuid.UUID
    event_id: uuid.UUID
    status: str = "queued"


class IncidentNoActionResolutionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    outcome: (
        Literal["no_issue_found", "already_corrected", "guidance_provided", "resolved_externally"]
        | None
    ) = None
    customer_message: str | None = Field(default=None, min_length=10, max_length=1000)
    next_steps: str | None = Field(default=None, min_length=10, max_length=500)
    reason: str = Field(
        min_length=10,
        max_length=1000,
        description="Explain why no operational action is required.",
    )

    @model_validator(mode="after")
    def complete_closure(self) -> "IncidentNoActionResolutionRequest":
        detailed = any(
            value is not None for value in (self.outcome, self.customer_message, self.next_steps)
        )
        if detailed and any(
            value is None for value in (self.outcome, self.customer_message, self.next_steps)
        ):
            raise ValueError("Detailed closure requires outcome, customer message, and next steps")
        return self


class IncidentClassificationResponse(BaseModel):
    incident_id: uuid.UUID
    status: IncidentStatus
    category: IncidentCategory
    priority: IncidentPriority
    confidence: float | None = Field(
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
    workflow_thread_id: str
    title: str
    description: str
    approval_required: bool = False
    similar_memories: list[IncidentMemoryRetrievalResult] = Field(
        default_factory=list,
    )

    memory_id: uuid.UUID | None = None
    memory_indexed: bool = False
    approval_request_id: uuid.UUID | None = None
    status: IncidentStatus
    category: IncidentCategory
    priority: IncidentPriority
    classification_confidence: float | None = Field(
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
