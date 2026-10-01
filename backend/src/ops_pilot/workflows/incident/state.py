import uuid
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.tools.schemas import (
    ToolCallRequest,
    ToolExecutionResult,
)


class IncidentInvestigationState(TypedDict):
    organization_id: uuid.UUID
    incident_id: uuid.UUID

    title: NotRequired[str]
    description: NotRequired[str]

    status: NotRequired[IncidentStatus]
    category: NotRequired[IncidentCategory]
    priority: NotRequired[IncidentPriority]
    classification_confidence: NotRequired[float]

    retrieval_query: NotRequired[str]
    evidence: NotRequired[list[RetrievalResult]]
    subject_customer_id: NotRequired[uuid.UUID | None]

    tool_round: NotRequired[int]
    pending_tool_call: NotRequired[ToolCallRequest | None]
    tool_results: NotRequired[list[ToolExecutionResult]]

    needs_more_information: NotRequired[bool]
    clarification_question: NotRequired[str | None]
    analysis: NotRequired[str]
    recommended_action: NotRequired[str]


@dataclass
class IncidentGraphContext:
    session: AsyncSession
