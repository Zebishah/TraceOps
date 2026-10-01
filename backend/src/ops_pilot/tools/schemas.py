from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ops_pilot.models.order import OrderStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransactionStatus,
    PaymentTransactionType,
)


class OperationalToolName(StrEnum):
    LIST_CUSTOMER_ORDERS = "list_customer_orders"
    GET_ORDER = "get_order"
    LIST_ORDER_PAYMENTS = "list_order_payments"
    GET_TRANSACTION = "get_transaction"


class ListCustomerOrdersInput(BaseModel):
    limit: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum number of recent customer orders to inspect.",
    )


class GetOrderInput(BaseModel):
    order_id: str = Field(
        min_length=1,
        description="The external order identifier to inspect.",
    )


class ListOrderPaymentsInput(BaseModel):
    order_id: str = Field(
        min_length=1,
        description="The external order identifier whose payments should be inspected.",
    )


class GetTransactionInput(BaseModel):
    transaction_id: str = Field(
        min_length=1,
        description="The external payment transaction identifier to inspect.",
    )


class OperationalOrderData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_order_id: str
    product_name: str | None
    total_amount: Decimal
    currency: str
    status: OrderStatus
    ordered_at: datetime


class PaymentTransactionData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_transaction_id: str
    provider: str
    transaction_type: PaymentTransactionType
    amount: Decimal
    currency: str
    status: PaymentTransactionStatus
    processed_at: datetime | None


class ToolCallRequest(BaseModel):
    call_id: str
    tool_name: OperationalToolName
    arguments: dict[str, object]


class ToolExecutionResult(BaseModel):
    call_id: str | None = None
    tool_name: OperationalToolName
    success: bool
    content: str
