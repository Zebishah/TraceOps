import uuid
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.schemas.action_execution import RefundExecutionResult
from ops_pilot.services.automation_events import (
    dispatch_customer_recovery_automation,
)


@pytest.mark.asyncio
async def test_simulated_refund_notification_uses_safe_wording() -> None:
    organization_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    customer = Mock()
    customer.id = customer_id
    customer.full_name = "Demo Customer"
    customer.email = "demo@example.com"

    result = Mock()
    result.scalar_one_or_none.return_value = customer

    session_mock = AsyncMock(spec=AsyncSession)
    session_mock.execute.return_value = result

    execution = RefundExecutionResult(
        source_transaction_id="DEMO-CHARGE-123",
        refund_transaction_id="DEMO-REFUND-123",
        amount=Decimal("100.00"),
        currency="USD",
        already_executed=False,
    )

    with patch(
        "ops_pilot.services.automation_events.send_n8n_event",
        new_callable=AsyncMock,
    ) as send_event:
        await dispatch_customer_recovery_automation(
            session=cast(AsyncSession, session_mock),
            organization_id=organization_id,
            incident_id=uuid.uuid4(),
            title="Duplicate payment",
            category="payment",
            priority="high",
            customer_id=customer_id,
            execution=execution,
        )

    send_event.assert_awaited_once()

    kwargs = send_event.await_args.kwargs

    assert kwargs["webhook_path"] == "incident-customer-recovery"

    event = kwargs["event"]

    assert event.event_type == "incident.customer_recovery"
    assert event.organization_id == organization_id

    resolution = event.payload.resolution.lower()

    assert "simulated refund" in resolution
    assert "internal ledger" in resolution
    assert "no external payment provider was contacted" in resolution

    assert event.payload.refund_amount == Decimal("100.00")
    assert event.payload.currency == "USD"
