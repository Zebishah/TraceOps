from ops_pilot.evaluation.models import (
    EvaluationCaseResult,
    EvaluationStatus,
    EvaluationSuiteResult,
)
from ops_pilot.evaluation.reporting import (
    build_evaluation_report,
    suite_meets_threshold,
)


def _suite(
    *,
    name: str,
    pass_rate: float,
) -> EvaluationSuiteResult:
    total_cases = 8
    passed_cases = round(total_cases * pass_rate)

    return EvaluationSuiteResult(
        suite_name=name,
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=(total_cases - passed_cases),
        pass_rate=pass_rate,
        cases=[
            EvaluationCaseResult(
                case_id="case",
                status=EvaluationStatus.PASSED,
                checks=[],
            )
        ],
    )


def test_safety_suite_requires_perfect_score() -> None:
    suite = _suite(
        name="hitl_dangerous_action_safety",
        pass_rate=0.99,
    )

    assert suite_meets_threshold(suite) is False


def test_classification_threshold_allows_seven_of_eight() -> None:
    suite = _suite(
        name="incident_classification",
        pass_rate=0.875,
    )

    assert suite_meets_threshold(suite) is True


def test_report_fails_when_suite_below_threshold() -> None:
    suites = [
        _suite(
            name="duplicate_payment_detection",
            pass_rate=1.0,
        ),
        _suite(
            name="tool_selection",
            pass_rate=0.5,
        ),
    ]

    report = build_evaluation_report(suites)

    assert report["passed"] is False
    assert report["total_suites"] == 2
    assert report["failed_suites"] == 1
