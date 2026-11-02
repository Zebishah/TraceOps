from decimal import Decimal
from unittest.mock import Mock

import pytest

import ops_pilot.ai.incident_memory_writer as writer
from ops_pilot.schemas.action_execution import RefundExecutionResult


@pytest.mark.asyncio
async def test_simulated_refund_memory_does_not_access_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_model = Mock()
    monkeypatch.setattr(writer, "get_chat_model", get_model)

    result = await writer.generate_incident_memory(
        title="Duplicate payment",
        description="Synthetic payment case.",
        category="payment",
        priority="high",
        analysis="Two matching charges were verified.",
        recommendation="Record an approved simulated refund.",
        tool_results=[],
        execution=RefundExecutionResult(
            source_transaction_id="TXN-DUPLICATE",
            refund_transaction_id="refund-test",
            amount=Decimal("100.00"),
            currency="USD",
            already_executed=False,
        ),
    )

    get_model.assert_not_called()
    assert "internal ledger" in result.summary
    assert "refund-test" in result.resolution
    assert "No external payment provider was contacted" in result.resolution
    assert "no real money was moved" in result.resolution
