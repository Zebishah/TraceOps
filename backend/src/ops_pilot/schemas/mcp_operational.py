import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ops_pilot.schemas.incident_memories import (
    IncidentMemoryRetrievalResult,
)
from ops_pilot.tools.schemas import (
    OperationalOrderData,
    PaymentTransactionData,
)


class MCPCustomer(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: uuid.UUID
    external_customer_id: str
    email: str | None
    full_name: str | None
    created_at: datetime
    updated_at: datetime


class MCPCustomerResponse(BaseModel):
    customer: MCPCustomer | None


class MCPOrdersResponse(BaseModel):
    orders: list[OperationalOrderData]


class MCPOrderResponse(BaseModel):
    order: OperationalOrderData | None


class MCPPaymentsResponse(BaseModel):
    payments: list[PaymentTransactionData]


class MCPPaymentResponse(BaseModel):
    payment: PaymentTransactionData | None


class MCPIncidentMemoryResponse(BaseModel):
    incident_id: uuid.UUID
    memories: list[IncidentMemoryRetrievalResult]
