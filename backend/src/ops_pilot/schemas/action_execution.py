from decimal import Decimal

from pydantic import BaseModel


class RefundExecutionResult(BaseModel):
    source_transaction_id: str
    refund_transaction_id: str

    amount: Decimal
    currency: str

    already_executed: bool = False
