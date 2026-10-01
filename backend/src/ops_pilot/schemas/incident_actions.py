from decimal import Decimal

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)

from ops_pilot.models.approval import (
    ApprovalActionType,
)


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

    reason: str = Field(
        min_length=1,
        max_length=1000,
    )

    @model_validator(mode="after")
    def validate_action_proposal(
        self,
    ) -> "IncidentActionProposal":
        if self.requires_approval:
            if (
                self.action_type is None
                or self.external_transaction_id is None
                or self.amount is None
                or self.currency is None
            ):
                raise ValueError("Approval-required proposal must include complete action details")

        else:
            if (
                self.action_type is not None
                or self.external_transaction_id is not None
                or self.amount is not None
                or self.currency is not None
            ):
                raise ValueError("Non-approval proposal must not contain executable action details")

        return self
