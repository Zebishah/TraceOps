from ops_pilot.evaluation.models import (
    EvaluationCaseResult,
    EvaluationCheck,
    EvaluationStatus,
    EvaluationSuiteResult,
)


def test_evaluation_suite_result() -> None:
    case = EvaluationCaseResult(
        case_id="example",
        status=EvaluationStatus.PASSED,
        checks=[
            EvaluationCheck(
                name="example_check",
                passed=True,
            )
        ],
    )

    result = EvaluationSuiteResult(
        suite_name="example",
        total_cases=1,
        passed_cases=1,
        failed_cases=0,
        pass_rate=1.0,
        cases=[case],
    )

    assert result.pass_rate == 1.0
    assert result.cases[0].status == EvaluationStatus.PASSED
