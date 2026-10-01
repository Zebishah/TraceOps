import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.services.operational_data import (
    get_operational_order,
    get_payment_transaction,
    list_customer_orders,
    list_order_payments,
)
from ops_pilot.tools.schemas import (
    GetOrderInput,
    GetTransactionInput,
    ListCustomerOrdersInput,
    ListOrderPaymentsInput,
    OperationalOrderData,
    OperationalToolName,
    PaymentTransactionData,
    ToolExecutionResult,
)


def _to_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def execute_list_customer_orders(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    tool_input: ListCustomerOrdersInput,
) -> ToolExecutionResult:
    orders = await list_customer_orders(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        limit=tool_input.limit,
    )

    content = [
        OperationalOrderData.model_validate(order).model_dump(mode="json") for order in orders
    ]

    return ToolExecutionResult(
        tool_name=OperationalToolName.LIST_CUSTOMER_ORDERS,
        success=True,
        content=_to_json(content),
    )


async def execute_get_order(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    tool_input: GetOrderInput,
) -> ToolExecutionResult:
    order = await get_operational_order(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        external_order_id=tool_input.order_id,
    )

    if order is None:
        return ToolExecutionResult(
            tool_name=OperationalToolName.GET_ORDER,
            success=False,
            content=_to_json(
                {
                    "error": "order_not_found",
                }
            ),
        )

    content = OperationalOrderData.model_validate(order).model_dump(mode="json")

    return ToolExecutionResult(
        tool_name=OperationalToolName.GET_ORDER,
        success=True,
        content=_to_json(content),
    )


async def execute_list_order_payments(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    tool_input: ListOrderPaymentsInput,
) -> ToolExecutionResult:
    payments = await list_order_payments(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        external_order_id=tool_input.order_id,
    )

    content = [
        PaymentTransactionData.model_validate(payment).model_dump(mode="json")
        for payment in payments
    ]

    return ToolExecutionResult(
        tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
        success=True,
        content=_to_json(content),
    )


async def execute_get_transaction(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    tool_input: GetTransactionInput,
) -> ToolExecutionResult:
    transaction = await get_payment_transaction(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        external_transaction_id=tool_input.transaction_id,
    )

    if transaction is None:
        return ToolExecutionResult(
            tool_name=OperationalToolName.GET_TRANSACTION,
            success=False,
            content=_to_json(
                {
                    "error": "transaction_not_found",
                }
            ),
        )

    content = PaymentTransactionData.model_validate(transaction).model_dump(mode="json")

    return ToolExecutionResult(
        tool_name=OperationalToolName.GET_TRANSACTION,
        success=True,
        content=_to_json(content),
    )
