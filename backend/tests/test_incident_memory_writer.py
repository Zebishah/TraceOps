import asyncio
from decimal import Decimal

import ops_pilot.ai.incident_memory_writer as memory_writer_module
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.action_execution import (
    RefundExecutionResult,
)
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
)
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryCreate,
)


class FakeChain:
    async def ainvoke(
        self,
        payload: dict[str, object],
    ) -> IncidentMemoryCreate:
        assert payload["title"] == "Customer charged twice"
        assert payload["category"] == "payment"
        assert payload["priority"] == "high"

        return IncidentMemoryCreate(
            summary=("The customer had two successful charges for the same order."),
            resolution=("The duplicate charge was refunded after human approval and verification."),
        )


class FakePrompt:
    def __or__(
        self,
        other: object,
    ) -> FakeChain:
        return FakeChain()


class FakeModel:
    def with_structured_output(
        self,
        schema: object,
        *,
        method: str,
        strict: bool,
    ) -> object:
        assert schema is IncidentMemoryCreate
        assert method == "json_schema"
        assert strict is True

        return object()


def test_generate_incident_memory_returns_structured_memory(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        memory_writer_module,
        "get_chat_model",
        lambda: FakeModel(),
    )

    monkeypatch.setattr(
        memory_writer_module,
        "INCIDENT_MEMORY_PROMPT",
        FakePrompt(),
    )

    result = asyncio.run(
        memory_writer_module.generate_incident_memory(
            title="Customer charged twice",
            description=("Two successful charges appeared for the same order."),
            category=IncidentCategory.PAYMENT,
            priority=IncidentPriority.HIGH,
            analysis="The second charge was confirmed as duplicate.",
            recommendation="Refund the duplicate transaction.",
            tool_results=[],
            execution=RefundExecutionResult(
                source_transaction_id="TXN-B",
                refund_transaction_id="refund-123",
                amount=Decimal("12000.00"),
                currency="PKR",
                already_executed=False,
            ),
        )
    )
    assert result.summary == (
        "A human-approved simulated refund was recorded "
        "and verified in OpsPilot's internal ledger. "
        "Source transaction: TXN-B. "
        "Amount: 12000.00 PKR."
    )

    assert result.resolution == (
        "Simulated refund refund-123 "
        "for 12000.00 PKR "
        "was recorded in OpsPilot's internal ledger against "
        "transaction TXN-B. "
        "No external payment provider was contacted and "
        "no real money was moved."
    )
