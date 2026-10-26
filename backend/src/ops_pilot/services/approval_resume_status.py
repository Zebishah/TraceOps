"""Read-only approval recovery status lookup."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.approval import ApprovalRequest
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
)
from ops_pilot.schemas.approval_resume_status import (
    ApprovalResumeStatusResponse,
)
from ops_pilot.services.approval_resume_recovery import MAX_ATTEMPTS


async def get_approval_resume_status(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
) -> ApprovalResumeStatusResponse | None:
    """Return the job only when all tenant identifiers match."""

    result = await session.execute(
        select(ApprovalResumeJob)
        .join(
            ApprovalRequest,
            ApprovalRequest.id == ApprovalResumeJob.approval_request_id,
        )
        .where(
            ApprovalResumeJob.organization_id == organization_id,
            ApprovalResumeJob.incident_id == incident_id,
            ApprovalResumeJob.approval_request_id == approval_request_id,
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.incident_id == incident_id,
        )
    )

    job = result.scalar_one_or_none()

    if job is None:
        return None

    status = ApprovalResumeJobStatus(job.status)

    quarantined = status == ApprovalResumeJobStatus.FAILED and job.attempts >= MAX_ATTEMPTS

    return ApprovalResumeStatusResponse(
        job_id=job.id,
        approval_request_id=job.approval_request_id,
        incident_id=job.incident_id,
        status=status,
        attempts=job.attempts,
        max_attempts=MAX_ATTEMPTS,
        quarantined=quarantined,
        next_attempt_at=(
            job.next_attempt_at
            if status
            in {
                ApprovalResumeJobStatus.PENDING,
                ApprovalResumeJobStatus.FAILED,
            }
            and not quarantined
            else None
        ),
        lease_expires_at=(
            job.lease_expires_at if status == ApprovalResumeJobStatus.PROCESSING else None
        ),
        completed_at=job.completed_at,
    )
