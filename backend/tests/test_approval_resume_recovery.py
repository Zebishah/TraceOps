import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.approval_resume_recovery as recovery
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJobStatus,
)


def test_job_statuses() -> None:
    assert ApprovalResumeJobStatus.PENDING == "pending"
    assert ApprovalResumeJobStatus.PROCESSING == "processing"
    assert ApprovalResumeJobStatus.COMPLETED == "completed"
    assert ApprovalResumeJobStatus.FAILED == "failed"


def test_recovery_configuration() -> None:
    assert recovery.MAX_ATTEMPTS > 0
    assert recovery.LEASE_SECONDS > 0
    assert recovery.BATCH_SIZE > 0


def test_claimed_job_preserves_identity() -> None:
    job_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    token = uuid.uuid4()

    job = recovery.ClaimedResumeJob(
        id=job_id,
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        approval_request_id=approval_id,
        lease_token=token,
        attempts=1,
    )

    assert job.id == job_id
    assert job.approval_request_id == approval_id
    assert job.lease_token == token
    assert job.attempts == 1


@pytest.mark.parametrize(
    "attempts,expected_delay",
    [
        (1, 30),
        (2, 60),
        (3, 120),
        (4, 240),
        (5, 480),
        (6, 900),
    ],
)
def test_retry_backoff(
    attempts: int,
    expected_delay: int,
) -> None:
    assert recovery.resume_retry_delay_seconds(attempts) == expected_delay


def test_complete_job_rejects_stale_token(
    monkeypatch,
) -> None:
    """A lost lease must not report successful completion."""

    class FakeResult:
        def scalar_one_or_none(self):
            return None

    session = AsyncMock()
    session.execute.return_value = FakeResult()

    class FakeFactory:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        recovery,
        "async_session_factory",
        FakeFactory,
    )

    job = recovery.ClaimedResumeJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        approval_request_id=uuid.uuid4(),
        lease_token=uuid.uuid4(),
        attempts=1,
    )

    completed = asyncio.run(recovery.complete_resume_job(job=job))

    assert completed is False
    session.commit.assert_awaited_once()
