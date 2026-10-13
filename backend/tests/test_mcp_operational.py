import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.models.order import OrderStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.services import mcp_operational

ORGANIZATION_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()


@pytest.mark.anyio
async def test_get_customer_is_tenant_scoped() -> None:
    session = AsyncMock()

    customer = SimpleNamespace(
        id=CUSTOMER_ID,
        external_customer_id="cus_123",
        email="customer@example.com",
        full_name="Test Customer",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    result = Mock()
    result.scalar_one_or_none.return_value = customer
    session.execute.return_value = result

    response = await mcp_operational.get_customer(
        session=session,
        organization_id=ORGANIZATION_ID,
        customer_id=CUSTOMER_ID,
    )

    assert response is not None
    assert response.id == CUSTOMER_ID
    assert response.external_customer_id == "cus_123"

    session.execute.assert_awaited_once()


@pytest.mark.anyio
async def test_list_customer_orders_reuses_operational_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    order = SimpleNamespace(
        external_order_id="order_123",
        product_name="Pro Plan",
        total_amount=Decimal("49.99"),
        currency="USD",
        status=OrderStatus.PAID,
        ordered_at=datetime.now(UTC),
    )

    fake_list = AsyncMock(
        return_value=[
            order,
        ]
    )

    monkeypatch.setattr(
        mcp_operational,
        "list_customer_orders",
        fake_list,
    )

    response = await mcp_operational.list_customer_orders_for_mcp(
        session=session,
        organization_id=ORGANIZATION_ID,
        customer_id=CUSTOMER_ID,
        limit=10,
    )

    assert len(response) == 1
    assert response[0].external_order_id == "order_123"

    fake_list.assert_awaited_once_with(
        session=session,
        organization_id=ORGANIZATION_ID,
        customer_id=CUSTOMER_ID,
        limit=10,
    )


@pytest.mark.anyio
async def test_list_order_payments_reuses_operational_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    payment = SimpleNamespace(
        external_transaction_id="txn_123",
        provider="stripe",
        transaction_type=PaymentTransactionType.CHARGE,
        amount=Decimal("49.99"),
        currency="USD",
        status=PaymentTransactionStatus.SUCCEEDED,
        processed_at=datetime.now(UTC),
    )

    fake_list = AsyncMock(
        return_value=[
            payment,
        ]
    )

    monkeypatch.setattr(
        mcp_operational,
        "list_order_payments",
        fake_list,
    )

    response = await mcp_operational.list_order_payments_for_mcp(
        session=session,
        organization_id=ORGANIZATION_ID,
        customer_id=CUSTOMER_ID,
        external_order_id="order_123",
    )

    assert len(response) == 1
    assert response[0].external_transaction_id == "txn_123"

    fake_list.assert_awaited_once_with(
        session=session,
        organization_id=ORGANIZATION_ID,
        customer_id=CUSTOMER_ID,
        external_order_id="order_123",
    )


@pytest.mark.anyio
async def test_incident_memory_requires_existing_categorized_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    fake_get_incident = AsyncMock(
        return_value=None,
    )

    fake_retrieve = AsyncMock()

    monkeypatch.setattr(
        mcp_operational,
        "get_incident_detail",
        fake_get_incident,
    )

    monkeypatch.setattr(
        mcp_operational,
        "retrieve_similar_incident_memories",
        fake_retrieve,
    )

    response = await mcp_operational.search_incident_memory_for_mcp(
        session=session,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
        limit=3,
    )

    assert response == []

    fake_retrieve.assert_not_awaited()
