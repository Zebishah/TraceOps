from ops_pilot.evaluation.tool_selection import (
    evaluate_tool_selection,
)


def test_tool_selection_evaluation_suite() -> None:
    result = evaluate_tool_selection()

    assert result.total_cases == 6
    assert result.passed_cases == 6
    assert result.failed_cases == 0
    assert result.pass_rate == 1.0
