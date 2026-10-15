from ops_pilot.evaluation.hitl_safety import (
    evaluate_hitl_safety,
)


def test_hitl_safety_evaluation_suite() -> None:
    result = evaluate_hitl_safety()

    assert result.total_cases == 6
    assert result.passed_cases == 6
    assert result.failed_cases == 0
    assert result.pass_rate == 1.0
