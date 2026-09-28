import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ops_pilot.models.incident import IncidentPriority, IncidentStatus


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    title: str = Field(
        min_length=1,
        max_length=200,
    )

    description: str = Field(
        min_length=1,
    )


class IncidentResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: uuid.UUID
    organization_id: uuid.UUID
    created_by_user_id: uuid.UUID

    title: str
    description: str

    status: IncidentStatus
    category: str | None
    priority: IncidentPriority | None

    created_at: datetime
    updated_at: datetime
