import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ops_pilot.models.background_job import (
    BackgroundJobStatus,
    BackgroundJobType,
)


class BackgroundJobResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: uuid.UUID
    organization_id: uuid.UUID
    created_by_user_id: uuid.UUID | None

    job_type: BackgroundJobType
    status: BackgroundJobStatus

    resource_id: uuid.UUID | None

    progress_percent: int = Field(
        ge=0,
        le=100,
    )

    error_message: str | None

    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class BackgroundJobEventData(BaseModel):
    job_id: uuid.UUID
    dispatch_id: uuid.UUID
    organization_id: uuid.UUID
    resource_id: uuid.UUID
