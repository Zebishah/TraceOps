import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class IncidentResolvedPayload(BaseModel):
    resolution_reason: str | None = None
    incident_id: uuid.UUID
    title: str
    category: str | None
    priority: str | None
    customer_id: uuid.UUID | None
    customer_email: str | None
    customer_name: str | None


class HighRiskIncidentPayload(BaseModel):
    incident_id: uuid.UUID
    title: str
    priority: str
    category: str | None


class DocumentIndexingFailedPayload(BaseModel):
    document_id: uuid.UUID
    job_id: uuid.UUID
    filename: str
    error_message: str


class CustomerRecoveryPayload(BaseModel):
    incident_id: uuid.UUID
    title: str
    category: str
    priority: str

    customer_id: uuid.UUID
    customer_name: str | None
    customer_email: str | None

    resolution: str
    action_type: str

    source_transaction_id: str
    refund_transaction_id: str
    refund_amount: Decimal
    currency: str


class IncidentAcknowledgedPayload(BaseModel):
    incident_id: uuid.UUID
    responder_id: uuid.UUID


class AutomationEvent(BaseModel):
    event_id: uuid.UUID
    event_type: str
    organization_id: uuid.UUID
    occurred_at: datetime
    payload: (
        IncidentResolvedPayload
        | IncidentAcknowledgedPayload
        | HighRiskIncidentPayload
        | DocumentIndexingFailedPayload
        | CustomerRecoveryPayload
    )
