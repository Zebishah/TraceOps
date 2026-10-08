import uuid
from datetime import datetime

from pydantic import BaseModel


class IncidentResolvedPayload(BaseModel):
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


class AutomationEvent(BaseModel):
    event_id: uuid.UUID
    event_type: str
    organization_id: uuid.UUID
    occurred_at: datetime
    payload: IncidentResolvedPayload | HighRiskIncidentPayload | DocumentIndexingFailedPayload
