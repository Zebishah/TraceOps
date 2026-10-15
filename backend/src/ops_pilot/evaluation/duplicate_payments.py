import json
from dataclasses import dataclass

from ops_pilot.evaluation.models import (
    EvaluationCaseResult,
    EvaluationCheck,
    EvaluationStatus,
    EvaluationSuiteResult,
)
from ops_pilot.services.duplicate_payment_detection import (
    detect_duplicate_payment_candidate,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolExecutionResult,
)


@dataclass(frozen=True)
class DuplicatePaymentEvaluationCase:
    case_id: str
    payments: list[dict[str, object]]
    expected_duplicate_transaction_id: str | None


def _tool_result(
    payments: list[dict[str, object]],
) -> ToolExecutionResult:
    return ToolExecutionResult(
        call_id="evaluation",
        tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
        arguments={
            "order_id": "ORD-EVAL",
        },
        success=True,
        content=json.dumps(payments),
    )


def _cases() -> list[DuplicatePaymentEvaluationCase]:
    return [
        DuplicatePaymentEvaluationCase(
            case_id="matching_duplicate_within_window",
            payments=[
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:00:00Z",
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:01:00Z",
                },
            ],
            expected_duplicate_transaction_id="TXN-B",
        ),
        DuplicatePaymentEvaluationCase(
            case_id="different_amounts_not_duplicate",
            payments=[
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:00:00Z",
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "15000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:01:00Z",
                },
            ],
            expected_duplicate_transaction_id=None,
        ),
        DuplicatePaymentEvaluationCase(
            case_id="too_far_apart_not_duplicate",
            payments=[
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:00:00Z",
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T11:00:00Z",
                },
            ],
            expected_duplicate_transaction_id=None,
        ),
        DuplicatePaymentEvaluationCase(
            case_id="different_provider_not_duplicate",
            payments=[
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:00:00Z",
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "adyen",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:01:00Z",
                },
            ],
            expected_duplicate_transaction_id=None,
        ),
        DuplicatePaymentEvaluationCase(
            case_id="ambiguous_three_charges_not_duplicate",
            payments=[
                {
                    "external_transaction_id": "TXN-A",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:00:00Z",
                },
                {
                    "external_transaction_id": "TXN-B",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:01:00Z",
                },
                {
                    "external_transaction_id": "TXN-C",
                    "provider": "stripe",
                    "transaction_type": "charge",
                    "amount": "12000.00",
                    "currency": "PKR",
                    "status": "succeeded",
                    "processed_at": "2026-10-15T10:02:00Z",
                },
            ],
            expected_duplicate_transaction_id=None,
        ),
    ]


def evaluate_duplicate_payment_detection() -> EvaluationSuiteResult:
    results: list[EvaluationCaseResult] = []

    for case in _cases():
        candidate = detect_duplicate_payment_candidate(
            tool_results=[
                _tool_result(case.payments),
            ],
        )

        actual_transaction_id = (
            candidate.duplicate_transaction_id if candidate is not None else None
        )

        passed = actual_transaction_id == case.expected_duplicate_transaction_id

        results.append(
            EvaluationCaseResult(
                case_id=case.case_id,
                status=(EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED),
                checks=[
                    EvaluationCheck(
                        name="duplicate_transaction",
                        passed=passed,
                        details=(
                            "expected="
                            f"{case.expected_duplicate_transaction_id}, "
                            f"actual={actual_transaction_id}"
                        ),
                    )
                ],
            )
        )

    passed_cases = sum(case.status == EvaluationStatus.PASSED for case in results)

    total_cases = len(results)

    return EvaluationSuiteResult(
        suite_name="duplicate_payment_detection",
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        pass_rate=(passed_cases / total_cases if total_cases else 0.0),
        cases=results,
    )
