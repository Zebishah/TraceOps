import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.automation_events as automation
from ops_pilot.schemas.action_execution import RefundExecutionResult


@pytest.mark.asyncio
async def test_customer_recovery_dispatch_uses_persisted_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()

    execution = RefundExecutionResult(
        source_transaction_id="charge-123",
        refund_transaction_id="refund-123",
        amount=Decimal("100.00"),
        currency="USD",
        already_executed=False,
    )

    expected_id = automation.build_automation_event_id(
        organization_id=organization_id,
        event_type="incident.customer_recovery",
        resource_key=execution.refund_transaction_id,
    )

    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = SimpleNamespace(
        organization_id=organization_id,
        event_type="incident.customer_recovery",
        webhook_path="incident-customer-recovery",
    )

    deliver = AsyncMock(return_value=True)

    monkeypatch.setattr(
        automation,
        "deliver_automation",
        deliver,
    )

    await automation.dispatch_customer_recovery_automation(
        session=cast(AsyncSession, session),
        organization_id=organization_id,
        incident_id=uuid.uuid4(),
        title="Duplicate payment",
        category="payment",
        priority="high",
        customer_id=uuid.uuid4(),
        execution=execution,
    )

    session.get.assert_awaited_once_with(
        automation.AutomationDelivery,
        expected_id,
    )

    deliver.assert_awaited_once_with(
        delivery_id=expected_id,
    )


@pytest.mark.asyncio
async def test_missing_customer_recovery_outbox_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = None

    deliver = AsyncMock()
    monkeypatch.setattr(
        automation,
        "deliver_automation",
        deliver,
    )

    execution = RefundExecutionResult(
        source_transaction_id="charge-123",
        refund_transaction_id="refund-123",
        amount=Decimal("100.00"),
        currency="USD",
        already_executed=True,
    )

    with pytest.raises(
        RuntimeError,
        match="outbox event missing",
    ):
        await automation.dispatch_customer_recovery_automation(
            session=cast(AsyncSession, session),
            organization_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            title="Duplicate payment",
            category="payment",
            priority="high",
            customer_id=uuid.uuid4(),
            execution=execution,
        )

    deliver.assert_not_awaited()
