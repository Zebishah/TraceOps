"""Public status response for durable approval recovery jobs."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from ops_pilot.models.approval_resume_job import ApprovalResumeJobStatus


class ApprovalResumeStatusResponse(BaseModel):
    job_id: uuid.UUID
    approval_request_id: uuid.UUID
    incident_id: uuid.UUID
    status: ApprovalResumeJobStatus
    attempts: int
    max_attempts: int
    quarantined: bool
    next_attempt_at: datetime | None
    lease_expires_at: datetime | None
    completed_at: datetime | None
