"""Approval checkpoint identity validation tests."""

import uuid
from types import SimpleNamespace

import pytest

from ops_pilot.services.approval_resume_processor import (
    validate_resume_checkpoint,
)
from ops_pilot.services.approval_resume_recovery import (
    ClaimedResumeJob,
)


def make_job() -> ClaimedResumeJob:
    return ClaimedResumeJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        approval_request_id=uuid.uuid4(),
        lease_token=uuid.uuid4(),
        attempts=1,
    )


def snapshot_for(job: ClaimedResumeJob):
    return SimpleNamespace(
        values={
            "organization_id": job.organization_id,
            "incident_id": job.incident_id,
            "approval_request_id": job.approval_request_id,
        }
    )


def test_matching_checkpoint_is_valid():
    job = make_job()

    validate_resume_checkpoint(
        snapshot=snapshot_for(job),
        job=job,
    )


@pytest.mark.parametrize(
    "field",
    [
        "organization_id",
        "incident_id",
        "approval_request_id",
    ],
)
def test_mismatched_checkpoint_is_rejected(field):
    job = make_job()
    snapshot = snapshot_for(job)

    snapshot.values[field] = uuid.uuid4()

    with pytest.raises(RuntimeError, match="mismatch"):
        validate_resume_checkpoint(
            snapshot=snapshot,
            job=job,
        )


def test_missing_checkpoint_is_rejected():
    job = make_job()

    with pytest.raises(
        RuntimeError,
        match="no valid persisted state",
    ):
        validate_resume_checkpoint(
            snapshot=SimpleNamespace(values=None),
            job=job,
        )


def test_missing_approval_id_is_rejected():
    job = make_job()
    snapshot = snapshot_for(job)

    del snapshot.values["approval_request_id"]

    with pytest.raises(
        RuntimeError,
        match="missing valid approval_request_id",
    ):
        validate_resume_checkpoint(
            snapshot=snapshot,
            job=job,
        )
