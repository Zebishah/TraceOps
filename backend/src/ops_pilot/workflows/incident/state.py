import uuid
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.incident import (
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.schemas.action_execution import (
    RefundExecutionResult,
)
from ops_pilot.schemas.approvals import (
    ApprovalResumeDecision,
)
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
)
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
)
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryRetrievalResult,
)
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.tools.schemas import (
    ToolCallRequest,
    ToolExecutionResult,
)


class IncidentInvestigationState(TypedDict):
    organization_id: uuid.UUID
    incident_id: uuid.UUID
    workflow_thread_id: str

    title: NotRequired[str]
    description: NotRequired[str]

    status: NotRequired[IncidentStatus]
    category: NotRequired[IncidentCategory]
    priority: NotRequired[IncidentPriority]
    classification_confidence: NotRequired[float]

    retrieval_query: NotRequired[str]
    evidence: NotRequired[list[RetrievalResult]]
    subject_customer_id: NotRequired[uuid.UUID | None]
    refund_execution: NotRequired[RefundExecutionResult | None]
    refund_verified: NotRequired[bool]
    tool_round: NotRequired[int]
    pending_tool_call: NotRequired[ToolCallRequest | None]
    tool_results: NotRequired[list[ToolExecutionResult]]
    similar_memories: NotRequired[list[IncidentMemoryRetrievalResult]]

    memory_id: NotRequired[uuid.UUID | None]
    memory_indexed: NotRequired[bool]
    needs_more_information: NotRequired[bool]
    clarification_question: NotRequired[str | None]

    analysis: NotRequired[str]
    recommended_action: NotRequired[str]

    proposed_action: NotRequired[IncidentActionProposal | None]

    approval_required: NotRequired[bool]

    approval_request_id: NotRequired[uuid.UUID | None]

    approval_decision: NotRequired[ApprovalResumeDecision | None]


@dataclass
class IncidentGraphContext:
    session: AsyncSession
