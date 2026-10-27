from decimal import Decimal

import pytest
from pydantic import ValidationError

from ops_pilot.models.approval import ApprovalActionType
from ops_pilot.schemas.incident_actions import IncidentActionProposal


def make_proposal(amount: Decimal) -> IncidentActionProposal:
    return IncidentActionProposal(
        requires_approval=True,
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        external_transaction_id="DEMO-CHARGE-123",
        amount=amount,
        currency="USD",
        reason="Verified duplicate payment.",
    )


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("100.001"),
        Decimal("10000000000.00"),
    ],
)
def test_invalid_financial_amount_is_rejected(
    amount: Decimal,
) -> None:
    with pytest.raises(ValidationError):
        make_proposal(amount)


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0.01"),
        Decimal("100.00"),
        Decimal("9999999999.99"),
    ],
)
def test_valid_financial_amount_is_accepted(
    amount: Decimal,
) -> None:
    proposal = make_proposal(amount)

    assert proposal.amount == amount
    assert proposal.requires_approval is True
    assert proposal.action_type == ApprovalActionType.REFUND_TRANSACTION


@pytest.mark.parametrize(
    "currency",
    [
        "usd",
        "US",
        "USDD",
        "12A",
    ],
)
def test_invalid_currency_is_rejected(
    currency: str,
) -> None:
    with pytest.raises(ValidationError):
        IncidentActionProposal(
            requires_approval=True,
            action_type=ApprovalActionType.REFUND_TRANSACTION,
            external_transaction_id="DEMO-CHARGE-123",
            amount=Decimal("100.00"),
            currency=currency,
            reason="Verified duplicate payment.",
        )


def test_non_approval_proposal_cannot_contain_refund_fields() -> None:
    with pytest.raises(ValidationError):
        IncidentActionProposal(
            requires_approval=False,
            action_type=ApprovalActionType.REFUND_TRANSACTION,
            external_transaction_id="DEMO-CHARGE-123",
            amount=Decimal("100.00"),
            currency="USD",
            reason="No action needed.",
        )


def test_approval_proposal_requires_complete_fields() -> None:
    with pytest.raises(ValidationError):
        IncidentActionProposal(
            requires_approval=True,
            reason="Missing financial details.",
        )
