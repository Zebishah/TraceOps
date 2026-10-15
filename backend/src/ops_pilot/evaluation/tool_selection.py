import json
from dataclasses import dataclass

from ops_pilot.evaluation.models import (
    EvaluationCaseResult,
    EvaluationCheck,
    EvaluationStatus,
    EvaluationSuiteResult,
)
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
)
from ops_pilot.services.incident_tool_planning import (
    required_operational_tool,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolExecutionResult,
)


@dataclass(frozen=True)
class ToolSelectionEvaluationCase:
    case_id: str
    category: IncidentCategory
    tool_results: list[ToolExecutionResult]
    expected_tool: OperationalToolName | None
    expected_arguments: dict[str, object] | None


def _cases() -> list[ToolSelectionEvaluationCase]:
    return [
        ToolSelectionEvaluationCase(
            case_id="payment_requires_order_listing_first",
            category=IncidentCategory.PAYMENT,
            tool_results=[],
            expected_tool=(OperationalToolName.LIST_CUSTOMER_ORDERS),
            expected_arguments={
                "limit": 10,
            },
        ),
        ToolSelectionEvaluationCase(
            case_id="payment_requires_order_payments_after_order_found",
            category=IncidentCategory.PAYMENT,
            tool_results=[
                ToolExecutionResult(
                    call_id="orders",
                    tool_name=(OperationalToolName.LIST_CUSTOMER_ORDERS),
                    arguments={
                        "limit": 10,
                    },
                    success=True,
                    content=json.dumps(
                        [
                            {
                                "external_order_id": "ORD-123",
                            }
                        ]
                    ),
                )
            ],
            expected_tool=(OperationalToolName.LIST_ORDER_PAYMENTS),
            expected_arguments={
                "order_id": "ORD-123",
            },
        ),
        ToolSelectionEvaluationCase(
            case_id="payment_stops_after_required_tools_complete",
            category=IncidentCategory.PAYMENT,
            tool_results=[
                ToolExecutionResult(
                    call_id="orders",
                    tool_name=(OperationalToolName.LIST_CUSTOMER_ORDERS),
                    arguments={
                        "limit": 10,
                    },
                    success=True,
                    content=json.dumps(
                        [
                            {
                                "external_order_id": "ORD-123",
                            }
                        ]
                    ),
                ),
                ToolExecutionResult(
                    call_id="payments",
                    tool_name=(OperationalToolName.LIST_ORDER_PAYMENTS),
                    arguments={
                        "order_id": "ORD-123",
                    },
                    success=True,
                    content="[]",
                ),
            ],
            expected_tool=None,
            expected_arguments=None,
        ),
        ToolSelectionEvaluationCase(
            case_id="non_payment_has_no_required_tool",
            category=IncidentCategory.ACCESS,
            tool_results=[],
            expected_tool=None,
            expected_arguments=None,
        ),
        ToolSelectionEvaluationCase(
            case_id="failed_order_listing_is_retried",
            category=IncidentCategory.PAYMENT,
            tool_results=[
                ToolExecutionResult(
                    call_id="orders",
                    tool_name=(OperationalToolName.LIST_CUSTOMER_ORDERS),
                    arguments={
                        "limit": 10,
                    },
                    success=False,
                    content="temporary failure",
                )
            ],
            expected_tool=(OperationalToolName.LIST_CUSTOMER_ORDERS),
            expected_arguments={
                "limit": 10,
            },
        ),
        ToolSelectionEvaluationCase(
            case_id="malformed_order_payload_stops_safely",
            category=IncidentCategory.PAYMENT,
            tool_results=[
                ToolExecutionResult(
                    call_id="orders",
                    tool_name=(OperationalToolName.LIST_CUSTOMER_ORDERS),
                    arguments={
                        "limit": 10,
                    },
                    success=True,
                    content="not-json",
                )
            ],
            expected_tool=None,
            expected_arguments=None,
        ),
    ]


def evaluate_tool_selection() -> EvaluationSuiteResult:
    results: list[EvaluationCaseResult] = []

    for case in _cases():
        tool_call = required_operational_tool(
            category=case.category,
            tool_results=case.tool_results,
        )

        actual_tool = tool_call.tool_name if tool_call is not None else None

        actual_arguments = tool_call.arguments if tool_call is not None else None

        tool_passed = actual_tool == case.expected_tool

        arguments_passed = actual_arguments == case.expected_arguments

        passed = tool_passed and arguments_passed

        results.append(
            EvaluationCaseResult(
                case_id=case.case_id,
                status=(EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED),
                checks=[
                    EvaluationCheck(
                        name="tool_name",
                        passed=tool_passed,
                        details=(f"expected={case.expected_tool}, actual={actual_tool}"),
                    ),
                    EvaluationCheck(
                        name="arguments",
                        passed=arguments_passed,
                        details=(f"expected={case.expected_arguments}, actual={actual_arguments}"),
                    ),
                ],
            )
        )

    passed_cases = sum(result.status == EvaluationStatus.PASSED for result in results)

    total_cases = len(results)

    return EvaluationSuiteResult(
        suite_name="tool_selection",
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        pass_rate=(passed_cases / total_cases if total_cases else 0.0),
        cases=results,
    )
