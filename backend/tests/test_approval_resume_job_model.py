import uuid

from sqlalchemy import CheckConstraint, UniqueConstraint

from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
)


def test_default_resume_job_state() -> None:
    job = ApprovalResumeJob(
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        approval_request_id=uuid.uuid4(),
        status=ApprovalResumeJobStatus.PENDING.value,
        attempts=0,
    )

    assert job.status == "pending"
    assert job.attempts == 0
    assert job.lease_token is None
    assert job.completed_at is None


def test_resume_job_status_values() -> None:
    assert ApprovalResumeJobStatus.PENDING.value == "pending"
    assert ApprovalResumeJobStatus.PROCESSING.value == "processing"
    assert ApprovalResumeJobStatus.COMPLETED.value == "completed"
    assert ApprovalResumeJobStatus.FAILED.value == "failed"


def test_unique_job_per_approval_constraint() -> None:
    table = ApprovalResumeJob.__table__

    constraints = [
        constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
    ]

    assert any(constraint.name == "uq_approval_resume_jobs_approval" for constraint in constraints)


def test_job_state_constraints_exist() -> None:
    table = ApprovalResumeJob.__table__

    constraint_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_approval_resume_jobs_status" in constraint_names
    assert "ck_approval_resume_jobs_attempts" in constraint_names
