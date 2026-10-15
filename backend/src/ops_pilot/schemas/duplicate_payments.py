from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class DuplicatePaymentCandidate(BaseModel):
    order_id: str

    original_transaction_id: str
    duplicate_transaction_id: str

    amount: Decimal
    currency: str
    provider: str

    original_processed_at: datetime
    duplicate_processed_at: datetime

    seconds_apart: int
