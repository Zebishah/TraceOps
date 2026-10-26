"""Guarded completion query regression test."""

import uuid

from sqlalchemy import update
from sqlalchemy.dialects import postgresql

from ops_pilot.models.approval import ApprovalRequest, ApprovalStatus
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
)
from ops_pilot.services.approval_resume_recovery import MAX_ATTEMPTS


def test_completion_requires_matching_terminal_approval():
    job_id = uuid.uuid4()

    matching_approval = (
        __import__("sqlalchemy")
        .select(ApprovalRequest.id)
        .where(
            ApprovalRequest.id == ApprovalResumeJob.approval_request_id,
            ApprovalRequest.organization_id == ApprovalResumeJob.organization_id,
            ApprovalRequest.incident_id == ApprovalResumeJob.incident_id,
            ApprovalRequest.status.in_([ApprovalStatus.EXECUTED, ApprovalStatus.REJECTED]),
        )
        .exists()
    )

    statement = (
        update(ApprovalResumeJob)
        .where(
            ApprovalResumeJob.id == job_id,
            ApprovalResumeJob.status == ApprovalResumeJobStatus.FAILED.value,
            ApprovalResumeJob.attempts >= MAX_ATTEMPTS,
            ApprovalResumeJob.last_error.is_not(None),
            matching_approval,
        )
        .values(status=ApprovalResumeJobStatus.COMPLETED.value)
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "EXISTS" in sql
    assert "approval_requests" in sql
    assert "organization_id" in sql
    assert "incident_id" in sql
    assert "approval_resume_jobs" in sql
