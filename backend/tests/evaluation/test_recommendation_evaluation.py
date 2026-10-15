from unittest.mock import AsyncMock

import pytest

from ops_pilot.evaluation import recommendation


@pytest.mark.anyio
async def test_recommendation_evaluation_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = AsyncMock(
        side_effect=[
            (
                "Verify which transaction is the duplicate "
                "before taking any financial action. [TOOL 1]"
            ),
            ("Verify the customer's payment history before considering any refund."),
            (
                "Verify the transaction using trusted "
                "operational data before taking action. [TOOL 1]"
            ),
        ]
    )

    monkeypatch.setattr(
        recommendation,
        "recommend_incident_action",
        mock,
    )

    result = await recommendation.evaluate_recommendation_groundedness()

    assert result.total_cases == 3
    assert result.passed_cases == 3
    assert result.failed_cases == 0
    assert result.pass_rate == 1.0
    assert mock.await_count == 3
