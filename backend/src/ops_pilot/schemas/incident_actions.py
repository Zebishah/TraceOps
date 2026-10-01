from decimal import Decimal

from pydantic import BaseModel, Field

from ops_pilot.models.approval import ApprovalActionType


class IncidentActionProposal(BaseModel):
    requires_approval: bool

    action_type: ApprovalActionType | None = None

    external_transaction_id: str | None = Field(
        default=None,
        max_length=160,
    )

    amount: Decimal | None = None

    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )

    reason: str
