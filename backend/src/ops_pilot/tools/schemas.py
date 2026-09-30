from enum import StrEnum

from pydantic import BaseModel, Field


class OperationalToolName(StrEnum):
    GET_ORDER = "get_order"
    GET_TRANSACTION = "get_transaction"
    LIST_ORDER_PAYMENTS = "list_order_payments"


class GetOrderInput(BaseModel):
    order_id: str = Field(
        min_length=1,
        description="The external order identifier to inspect.",
    )


class GetTransactionInput(BaseModel):
    transaction_id: str = Field(
        min_length=1,
        description="The external payment transaction identifier to inspect.",
    )


class ListOrderPaymentsInput(BaseModel):
    order_id: str = Field(
        min_length=1,
        description="The external order identifier whose payments should be inspected.",
    )


class ToolExecutionResult(BaseModel):
    tool_name: OperationalToolName
    success: bool
    content: str
