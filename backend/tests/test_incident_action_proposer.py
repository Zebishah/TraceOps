from decimal import Decimal

from ops_pilot.models.approval import ApprovalActionType
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
)


def test_action_proposal_schema_accepts_refund() -> None:
    proposal = IncidentActionProposal(
        requires_approval=True,
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        external_transaction_id="TXN-123",
        amount=Decimal("12000.00"),
        currency="PKR",
        reason="Confirmed duplicate transaction.",
    )

    assert proposal.requires_approval is True

    assert proposal.action_type == ApprovalActionType.REFUND_TRANSACTION

    assert proposal.external_transaction_id == "TXN-123"

    assert proposal.amount == Decimal("12000.00")

    assert proposal.currency == "PKR"
