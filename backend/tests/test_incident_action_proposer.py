from decimal import Decimal

import pytest
from pydantic import ValidationError

from ops_pilot.models.approval import (
    ApprovalActionType,
)
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
)


def test_action_proposal_schema_accepts_refund() -> None:
    proposal = IncidentActionProposal(
        requires_approval=True,
        action_type=(ApprovalActionType.REFUND_TRANSACTION),
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

    assert proposal.reason == "Confirmed duplicate transaction."


def test_action_proposal_accepts_no_action_with_reason() -> None:
    proposal = IncidentActionProposal(
        requires_approval=False,
        action_type=None,
        external_transaction_id=None,
        amount=None,
        currency=None,
        reason="More verification is required.",
    )

    assert proposal.requires_approval is False

    assert proposal.action_type is None

    assert proposal.external_transaction_id is None

    assert proposal.amount is None

    assert proposal.currency is None

    assert proposal.reason == "More verification is required."


def test_action_proposal_requires_reason() -> None:
    invalid_data = {
        "requires_approval": False,
        "action_type": None,
        "external_transaction_id": None,
        "amount": None,
        "currency": None,
    }

    with pytest.raises(
        ValidationError,
    ):
        IncidentActionProposal.model_validate(invalid_data)


def test_action_proposal_requires_reason_for_refund() -> None:
    invalid_data = {
        "requires_approval": True,
        "action_type": (ApprovalActionType.REFUND_TRANSACTION),
        "external_transaction_id": "TXN-123",
        "amount": Decimal("12000.00"),
        "currency": "PKR",
        "reason": None,
    }

    with pytest.raises(
        ValidationError,
    ):
        IncidentActionProposal.model_validate(invalid_data)


def test_action_proposal_rejects_incomplete_refund() -> None:
    with pytest.raises(
        ValidationError,
    ):
        IncidentActionProposal(
            requires_approval=True,
            action_type=(ApprovalActionType.REFUND_TRANSACTION),
            external_transaction_id=None,
            amount=Decimal("12000.00"),
            currency="PKR",
            reason=("Duplicate payment was confirmed."),
        )


def test_no_action_rejects_executable_details() -> None:
    with pytest.raises(
        ValidationError,
    ):
        IncidentActionProposal(
            requires_approval=False,
            action_type=(ApprovalActionType.REFUND_TRANSACTION),
            external_transaction_id="TXN-123",
            amount=Decimal("12000.00"),
            currency="PKR",
            reason=("No action should contain executable details."),
        )
