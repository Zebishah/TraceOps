"""Recover queued Inngest dispatches after abandoned send leases."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from ops_pilot.db.session import async_session_factory
from ops_pilot.inngest.functions.document_processing import (
    DOCUMENT_PROCESSING_EVENT,
)
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.services.background_job_dispatch import (
    INCIDENT_ANALYSIS_EVENT,
    MEMORY_INDEXING_EVENT,
    _send_background_job_event,
)
from ops_pilot.services.background_jobs import (
    DISPATCH_LEASE_SECONDS,
)

logger = logging.getLogger(__name__)

RECOVERY_BATCH_SIZE = 25


@dataclass(frozen=True)
class RecoveryResult:
    candidates: int
    attempted: int
    failed: int


async def recover_abandoned_dispatches() -> RecoveryResult:
    """Attempt recovery of queued jobs with missing acknowledgements.

    The send lease is acquired atomically by the existing dispatcher.
    This sweep does not create new dispatch IDs.
    """
    now = datetime.now(UTC)
    stale_before = now - timedelta(
        seconds=DISPATCH_LEASE_SECONDS,
    )

    statement = (
        select(
            BackgroundJob.id,
            BackgroundJob.organization_id,
            BackgroundJob.resource_id,
            BackgroundJob.dispatch_id,
            BackgroundJob.job_type,
        )
        .where(
            BackgroundJob.status == BackgroundJobStatus.QUEUED,
            BackgroundJob.inngest_event_id.is_(None),
            BackgroundJob.dispatch_id.is_not(None),
            BackgroundJob.resource_id.is_not(None),
            or_(
                BackgroundJob.dispatch_lease_expires_at <= now,
                (
                    BackgroundJob.dispatch_lease_token.is_(None)
                    & (BackgroundJob.updated_at <= stale_before)
                ),
            ),
        )
        .order_by(BackgroundJob.updated_at)
        .limit(RECOVERY_BATCH_SIZE)
    )

    async with async_session_factory() as session:
        result = await session.execute(statement)
        candidates = result.all()

    attempted = 0
    failed = 0

    for (
        job_id,
        organization_id,
        resource_id,
        dispatch_id,
        job_type,
    ) in candidates:
        if resource_id is None or dispatch_id is None:
            continue

        if job_type == BackgroundJobType.DOCUMENT_PROCESSING:
            event_name = DOCUMENT_PROCESSING_EVENT
        elif job_type == BackgroundJobType.MEMORY_INDEXING:
            event_name = MEMORY_INDEXING_EVENT
        elif job_type == BackgroundJobType.INCIDENT_ANALYSIS:
            event_name = INCIDENT_ANALYSIS_EVENT
        else:
            logger.error(
                "unknown_background_job_type",
                extra={"job_id": str(job_id)},
            )
            failed += 1
            continue

        try:
            async with async_session_factory() as session:
                job = await session.get(
                    BackgroundJob,
                    job_id,
                )

                if job is None:
                    continue

                if job.organization_id != organization_id:
                    continue

                if job.resource_id != resource_id:
                    continue

                if job.dispatch_id != dispatch_id:
                    continue

                attempted += 1

                await _send_background_job_event(
                    session=session,
                    job=job,
                    dispatch_id=dispatch_id,
                    event_name=event_name,
                    organization_id=organization_id,
                    resource_id=resource_id,
                )
        except Exception:
            failed += 1
            logger.exception(
                "background_dispatch_recovery_failed",
                extra={
                    "job_id": str(job_id),
                    "organization_id": str(organization_id),
                    "dispatch_id": str(dispatch_id),
                },
            )

    return RecoveryResult(
        candidates=len(candidates),
        attempted=attempted,
        failed=failed,
    )


async def main() -> None:
    result = await recover_abandoned_dispatches()

    logger.info(
        "Background dispatch recovery completed: candidates=%d attempted=%d failed=%d",
        result.candidates,
        result.attempted,
        result.failed,
    )

    if result.failed:
        raise SystemExit(f"Dispatch recovery had {result.failed} failures")


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
