from ops_pilot.evaluation.duplicate_payments import (
    evaluate_duplicate_payment_detection,
)


def test_duplicate_payment_evaluation_suite_passes() -> None:
    result = evaluate_duplicate_payment_detection()

    assert result.total_cases == 5
    assert result.passed_cases == 5
    assert result.failed_cases == 0
    assert result.pass_rate == 1.0
