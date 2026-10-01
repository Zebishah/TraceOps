import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.tools.operational as operational_tools
from ops_pilot.models.order import OrderStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.tools.schemas import (
    GetTransactionInput,
    ListCustomerOrdersInput,
    OperationalToolName,
)


def test_list_customer_orders_uses_trusted_customer_context(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    async def fake_list_customer_orders(
        *,
        session,
        organization_id: uuid.UUID,
        customer_id: uuid.UUID,
        limit: int,
    ):
        assert organization_id == expected_organization_id
        assert customer_id == expected_customer_id
        assert limit == 10

        return [
            SimpleNamespace(
                external_order_id="ORD-101",
                product_name="Headphones",
                total_amount=Decimal("12000.00"),
                currency="PKR",
                status=OrderStatus.PAID,
                ordered_at=datetime.now(UTC),
            )
        ]

    expected_organization_id = organization_id
    expected_customer_id = customer_id

    monkeypatch.setattr(
        operational_tools,
        "list_customer_orders",
        fake_list_customer_orders,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    result = asyncio.run(
        operational_tools.execute_list_customer_orders(
            session=session,
            organization_id=organization_id,
            customer_id=customer_id,
            tool_input=ListCustomerOrdersInput(),
        )
    )

    assert result.success is True
    assert result.tool_name == OperationalToolName.LIST_CUSTOMER_ORDERS

    content = json.loads(result.content)

    assert content[0]["external_order_id"] == "ORD-101"


def test_get_transaction_returns_transaction(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    async def fake_get_payment_transaction(
        *,
        session,
        organization_id: uuid.UUID,
        customer_id: uuid.UUID,
        external_transaction_id: str,
    ):
        assert organization_id == expected_organization_id
        assert customer_id == expected_customer_id
        assert external_transaction_id == "TXN-2"

        return SimpleNamespace(
            external_transaction_id="TXN-2",
            provider="stripe",
            transaction_type=PaymentTransactionType.CHARGE,
            amount=Decimal("12000.00"),
            currency="PKR",
            status=PaymentTransactionStatus.SUCCEEDED,
            processed_at=datetime.now(UTC),
        )

    expected_organization_id = organization_id
    expected_customer_id = customer_id

    monkeypatch.setattr(
        operational_tools,
        "get_payment_transaction",
        fake_get_payment_transaction,
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    result = asyncio.run(
        operational_tools.execute_get_transaction(
            session=session,
            organization_id=organization_id,
            customer_id=customer_id,
            tool_input=GetTransactionInput(
                transaction_id="TXN-2",
            ),
        )
    )

    assert result.success is True
    assert result.tool_name == OperationalToolName.GET_TRANSACTION

    content = json.loads(result.content)

    assert content["external_transaction_id"] == "TXN-2"
    assert content["amount"] == "12000.00"


def test_get_transaction_returns_not_found(
    monkeypatch,
) -> None:
    async def fake_get_payment_transaction(**kwargs):
        return None

    monkeypatch.setattr(
        operational_tools,
        "get_payment_transaction",
        fake_get_payment_transaction,
    )

    result = asyncio.run(
        operational_tools.execute_get_transaction(
            session=cast(
                AsyncSession,
                AsyncMock(spec=AsyncSession),
            ),
            organization_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            tool_input=GetTransactionInput(
                transaction_id="UNKNOWN",
            ),
        )
    )

    assert result.success is False

    assert json.loads(result.content) == {
        "error": "transaction_not_found",
    }
