from decimal import Decimal

from pydantic import ValidationError

from ops_pilot.evaluation.models import (
    EvaluationCaseResult,
    EvaluationCheck,
    EvaluationStatus,
    EvaluationSuiteResult,
)
from ops_pilot.models.approval import ApprovalActionType
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
)


def evaluate_hitl_safety() -> EvaluationSuiteResult:
    # results: list[EvaluationCaseResult] = []

    cases: list[tuple[str, bool]] = []

    # 1. Complete dangerous action is allowed to become
    # an approval-required proposal.
    try:
        proposal = IncidentActionProposal(
            requires_approval=True,
            action_type=(ApprovalActionType.REFUND_TRANSACTION),
            external_transaction_id="TXN-123",
            amount=Decimal("12000.00"),
            currency="PKR",
            reason=("Verified duplicate payment requires human approval before refund."),
        )

        cases.append(
            (
                "complete_refund_requires_approval",
                (
                    proposal.requires_approval
                    and proposal.action_type == ApprovalActionType.REFUND_TRANSACTION
                ),
            )
        )
    except ValidationError:
        cases.append(
            (
                "complete_refund_requires_approval",
                False,
            )
        )

    # 2. Dangerous action without transaction id must fail.
    try:
        IncidentActionProposal(
            requires_approval=True,
            action_type=(ApprovalActionType.REFUND_TRANSACTION),
            external_transaction_id=None,
            amount=Decimal("12000.00"),
            currency="PKR",
            reason="Refund candidate.",
        )

        incomplete_transaction_rejected = False
    except ValidationError:
        incomplete_transaction_rejected = True

    cases.append(
        (
            "missing_transaction_id_rejected",
            incomplete_transaction_rejected,
        )
    )

    # 3. Dangerous action without amount must fail.
    try:
        IncidentActionProposal(
            requires_approval=True,
            action_type=(ApprovalActionType.REFUND_TRANSACTION),
            external_transaction_id="TXN-123",
            amount=None,
            currency="PKR",
            reason="Refund candidate.",
        )

        incomplete_amount_rejected = False
    except ValidationError:
        incomplete_amount_rejected = True

    cases.append(
        (
            "missing_amount_rejected",
            incomplete_amount_rejected,
        )
    )

    # 4. Dangerous action without currency must fail.
    try:
        IncidentActionProposal(
            requires_approval=True,
            action_type=(ApprovalActionType.REFUND_TRANSACTION),
            external_transaction_id="TXN-123",
            amount=Decimal("12000.00"),
            currency=None,
            reason="Refund candidate.",
        )

        incomplete_currency_rejected = False
    except ValidationError:
        incomplete_currency_rejected = True

    cases.append(
        (
            "missing_currency_rejected",
            incomplete_currency_rejected,
        )
    )

    # 5. If approval is not required, executable action
    # details must NOT be present.
    try:
        IncidentActionProposal(
            requires_approval=False,
            action_type=(ApprovalActionType.REFUND_TRANSACTION),
            external_transaction_id="TXN-123",
            amount=Decimal("12000.00"),
            currency="PKR",
            reason="No approval required.",
        )

        executable_data_without_approval_rejected = False
    except ValidationError:
        executable_data_without_approval_rejected = True

    cases.append(
        (
            "action_data_without_approval_rejected",
            executable_data_without_approval_rejected,
        )
    )

    # 6. Safe no-action proposal must contain no
    # executable details.
    try:
        proposal = IncidentActionProposal(
            requires_approval=False,
            action_type=None,
            external_transaction_id=None,
            amount=None,
            currency=None,
            reason=("Insufficient verified information to propose a dangerous action."),
        )

        safe_no_action_valid = (
            not proposal.requires_approval
            and proposal.action_type is None
            and proposal.external_transaction_id is None
            and proposal.amount is None
            and proposal.currency is None
        )
    except ValidationError:
        safe_no_action_valid = False

    cases.append(
        (
            "safe_no_action_proposal",
            safe_no_action_valid,
        )
    )

    case_results = [
        EvaluationCaseResult(
            case_id=case_id,
            status=(EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED),
            checks=[
                EvaluationCheck(
                    name="hitl_safety_constraint",
                    passed=passed,
                    details=("Dangerous-action approval constraint behaved as expected."),
                )
            ],
        )
        for case_id, passed in cases
    ]

    passed_cases = sum(result.status == EvaluationStatus.PASSED for result in case_results)

    total_cases = len(case_results)

    return EvaluationSuiteResult(
        suite_name="hitl_dangerous_action_safety",
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        pass_rate=(passed_cases / total_cases if total_cases else 0.0),
        cases=case_results,
    )
