import uuid
from datetime import datetime

from pydantic import BaseModel

from ops_pilot.models.incident import IncidentPriority, IncidentStatus


class MCPIncidentSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: IncidentStatus
    category: str | None
    priority: IncidentPriority | None
    subject_customer_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MCPIncidentSearchResponse(BaseModel):
    query: str | None = None
    incidents: list[MCPIncidentSummary]


class MCPIncidentDetail(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    description: str
    status: IncidentStatus
    category: str | None
    priority: IncidentPriority | None
    subject_customer_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
