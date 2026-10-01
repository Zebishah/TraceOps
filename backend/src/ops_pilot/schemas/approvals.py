import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalStatus,
)


class ApprovalDecisionRequest(BaseModel):
    approved: bool

    comment: str | None = Field(
        default=None,
        max_length=1000,
    )


class ApprovalResumeDecision(BaseModel):
    approval_request_id: uuid.UUID
    approved: bool
    decided_by_user_id: uuid.UUID

    comment: str | None = Field(
        default=None,
        max_length=1000,
    )


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: uuid.UUID
    organization_id: uuid.UUID
    incident_id: uuid.UUID

    workflow_thread_id: str

    action_type: ApprovalActionType
    action_payload: dict[str, object]
    reason: str

    status: ApprovalStatus

    decided_by_user_id: uuid.UUID | None
    decision_comment: str | None
    decided_at: datetime | None
    executed_at: datetime | None

    created_at: datetime
    updated_at: datetime
