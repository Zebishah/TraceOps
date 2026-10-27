"""Read-only health information for durable approval recovery."""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select

from ops_pilot.db.session import async_session_factory
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
)
from ops_pilot.services.approval_resume_recovery import MAX_ATTEMPTS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApprovalRecoveryHealth:
    pending: int
    processing: int
    retryable_failed: int
    quarantined: int
    oldest_quarantine_age_seconds: int | None

    def as_dict(self) -> dict[str, int | None]:
        return asdict(self)


async def get_approval_recovery_health() -> ApprovalRecoveryHealth:
    """Read durable job state without executing financial actions."""

    now = datetime.now(UTC)

    async with async_session_factory() as session:
        result = await session.execute(
            select(
                ApprovalResumeJob.status,
                func.count(ApprovalResumeJob.id),
            ).group_by(ApprovalResumeJob.status)
        )

        counts = dict(result.all())

        retryable_failed = await session.scalar(
            select(func.count(ApprovalResumeJob.id)).where(
                ApprovalResumeJob.status == ApprovalResumeJobStatus.FAILED.value,
                ApprovalResumeJob.attempts < MAX_ATTEMPTS,
            )
        )

        quarantined_count = await session.scalar(
            select(func.count(ApprovalResumeJob.id)).where(
                ApprovalResumeJob.status == ApprovalResumeJobStatus.FAILED.value,
                ApprovalResumeJob.attempts >= MAX_ATTEMPTS,
            )
        )

        oldest_quarantine = await session.scalar(
            select(func.min(ApprovalResumeJob.updated_at)).where(
                ApprovalResumeJob.status == ApprovalResumeJobStatus.FAILED.value,
                ApprovalResumeJob.attempts >= MAX_ATTEMPTS,
            )
        )

        await session.rollback()

    age_seconds: int | None = None

    if oldest_quarantine is not None:
        age_seconds = max(
            0,
            int((now - oldest_quarantine).total_seconds()),
        )

    return ApprovalRecoveryHealth(
        pending=int(counts.get(ApprovalResumeJobStatus.PENDING.value, 0)),
        processing=int(counts.get(ApprovalResumeJobStatus.PROCESSING.value, 0)),
        retryable_failed=int(retryable_failed or 0),
        quarantined=int(quarantined_count or 0),
        oldest_quarantine_age_seconds=age_seconds,
    )
