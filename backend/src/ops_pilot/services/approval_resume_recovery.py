"""Durable approval-resume job claiming and state transitions."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from ops_pilot.db.session import async_session_factory
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
)

MAX_ATTEMPTS = 5
LEASE_SECONDS = 120
BATCH_SIZE = 10


def resume_retry_delay_seconds(attempts: int) -> int:
    """Calculate bounded exponential retry delay."""
    if attempts < 1:
        raise ValueError("Attempts must be positive")

    delay: int = 30 * (2 ** (attempts - 1))

    return min(delay, 900)


@dataclass(frozen=True)
class ClaimedResumeJob:
    id: uuid.UUID
    organization_id: uuid.UUID
    incident_id: uuid.UUID
    approval_request_id: uuid.UUID
    lease_token: uuid.UUID
    attempts: int


async def renew_resume_job_lease(
    *,
    job: ClaimedResumeJob,
) -> bool:
    """Renew the lease only while the current owner holds it."""

    now = datetime.now(UTC)

    async with async_session_factory() as session:
        result = await session.execute(
            update(ApprovalResumeJob)
            .where(
                ApprovalResumeJob.id == job.id,
                ApprovalResumeJob.organization_id == job.organization_id,
                ApprovalResumeJob.status == ApprovalResumeJobStatus.PROCESSING.value,
                ApprovalResumeJob.lease_token == job.lease_token,
                ApprovalResumeJob.lease_expires_at > now,
            )
            .values(
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            )
            .returning(ApprovalResumeJob.id)
        )

        renewed = result.scalar_one_or_none() is not None
        await session.commit()

    return renewed


async def claim_resume_jobs(
    *,
    limit: int = BATCH_SIZE,
) -> list[ClaimedResumeJob]:
    """Claim due jobs without allowing concurrent database claims."""

    now = datetime.now(UTC)
    claimed: list[ClaimedResumeJob] = []

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(ApprovalResumeJob)
                .where(
                    ApprovalResumeJob.status.in_(
                        [
                            ApprovalResumeJobStatus.PENDING.value,
                            ApprovalResumeJobStatus.FAILED.value,
                        ]
                    ),
                    ApprovalResumeJob.attempts < MAX_ATTEMPTS,
                    ApprovalResumeJob.next_attempt_at <= now,
                )
                .order_by(
                    ApprovalResumeJob.next_attempt_at,
                    ApprovalResumeJob.created_at,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )

            jobs = result.scalars().all()

            for job in jobs:
                token = uuid.uuid4()

                job.status = ApprovalResumeJobStatus.PROCESSING.value
                job.attempts += 1
                job.lease_token = token
                job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)

                claimed.append(
                    ClaimedResumeJob(
                        id=job.id,
                        organization_id=job.organization_id,
                        incident_id=job.incident_id,
                        approval_request_id=job.approval_request_id,
                        lease_token=token,
                        attempts=job.attempts,
                    )
                )

    return claimed


async def complete_resume_job(
    *,
    job: ClaimedResumeJob,
) -> bool:
    """Only the owner of the current lease can complete a job."""

    now = datetime.now(UTC)

    async with async_session_factory() as session:
        result = await session.execute(
            update(ApprovalResumeJob)
            .where(
                ApprovalResumeJob.id == job.id,
                ApprovalResumeJob.lease_expires_at > now,
                ApprovalResumeJob.organization_id == job.organization_id,
                ApprovalResumeJob.lease_token == job.lease_token,
                ApprovalResumeJob.status == ApprovalResumeJobStatus.PROCESSING.value,
            )
            .values(
                status=ApprovalResumeJobStatus.COMPLETED.value,
                completed_at=now,
                lease_token=None,
                lease_expires_at=None,
                last_error=None,
            )
            .returning(ApprovalResumeJob.id)
        )

        completed_id = result.scalar_one_or_none()
        await session.commit()

    return completed_id is not None


async def fail_resume_job(
    *,
    job: ClaimedResumeJob,
    error: str,
    terminal: bool = False,
) -> bool:
    """Record failure and exponential retry delay."""

    now = datetime.now(UTC)

    delay_seconds = resume_retry_delay_seconds(job.attempts)

    async with async_session_factory() as session:
        result = await session.execute(
            update(ApprovalResumeJob)
            .where(
                ApprovalResumeJob.id == job.id,
                ApprovalResumeJob.lease_token == job.lease_token,
                ApprovalResumeJob.lease_expires_at > now,
                ApprovalResumeJob.organization_id == job.organization_id,
                ApprovalResumeJob.status == ApprovalResumeJobStatus.PROCESSING.value,
            )
            .values(
                status=ApprovalResumeJobStatus.FAILED.value,
                attempts=MAX_ATTEMPTS if terminal else job.attempts,
                next_attempt_at=now + timedelta(seconds=delay_seconds),
                lease_token=None,
                lease_expires_at=None,
                last_error=error[:1000],
            )
            .returning(ApprovalResumeJob.id)
        )

        failed_id = result.scalar_one_or_none()
        await session.commit()

    return failed_id is not None


async def quarantine_expired_resume_jobs(
    *,
    limit: int = BATCH_SIZE,
) -> int:
    """Quarantine abandoned jobs without replaying their actions.

    An expired lease does not prove the previous worker
    stopped before executing a refund.
    """
    now = datetime.now(UTC)

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(ApprovalResumeJob)
                .where(
                    ApprovalResumeJob.status == ApprovalResumeJobStatus.PROCESSING.value,
                    ApprovalResumeJob.lease_expires_at.is_not(None),
                    ApprovalResumeJob.lease_expires_at <= now,
                )
                .order_by(ApprovalResumeJob.lease_expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )

            jobs = result.scalars().all()

            for job in jobs:
                # Exhaust automatic attempts until a
                # checkpoint/payment reconciliation occurs.
                job.status = ApprovalResumeJobStatus.FAILED.value
                job.attempts = MAX_ATTEMPTS
                job.lease_token = None
                job.lease_expires_at = None
                job.last_error = (
                    "Execution lease expired; outcome uncertain. "
                    "Requires checkpoint and payment reconciliation."
                )

            return len(jobs)
