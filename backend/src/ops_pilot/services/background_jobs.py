import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)


async def create_background_job(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None,
    job_type: BackgroundJobType,
    resource_id: uuid.UUID,
    idempotency_key: str,
) -> BackgroundJob:
    statement = select(BackgroundJob).where(
        BackgroundJob.organization_id == organization_id,
        BackgroundJob.idempotency_key == idempotency_key,
    )

    result = await session.execute(statement)
    existing = result.scalar_one_or_none()

    if existing is not None:
        return existing

    job = BackgroundJob(
        organization_id=organization_id,
        created_by_user_id=created_by_user_id,
        job_type=job_type,
        status=BackgroundJobStatus.QUEUED,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
        progress_percent=0,
    )

    session.add(job)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()

        result = await session.execute(statement)
        existing = result.scalar_one_or_none()

        if existing is None:
            raise

        return existing
    except Exception:
        await session.rollback()
        raise

    await session.refresh(job)
    return job


async def get_background_job(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
) -> BackgroundJob | None:
    result = await session.execute(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.organization_id == organization_id,
        )
    )

    return result.scalar_one_or_none()


async def mark_background_job_processing(
    *,
    session: AsyncSession,
    job: BackgroundJob,
    progress_percent: int = 0,
) -> None:
    job.status = BackgroundJobStatus.PROCESSING
    job.progress_percent = progress_percent
    job.error_message = None

    if job.started_at is None:
        job.started_at = datetime.now(
            UTC,
        )

    await session.commit()
    await session.refresh(job)


async def mark_background_job_succeeded(
    *,
    session: AsyncSession,
    job: BackgroundJob,
) -> None:
    job.status = BackgroundJobStatus.SUCCEEDED
    job.progress_percent = 100
    job.error_message = None
    job.completed_at = datetime.now(
        UTC,
    )

    await session.commit()
    await session.refresh(job)


async def mark_background_job_failed(
    *,
    session: AsyncSession,
    job: BackgroundJob,
    error_message: str,
) -> None:
    job.status = BackgroundJobStatus.FAILED
    job.error_message = error_message[:1000]
    job.completed_at = datetime.now(
        UTC,
    )

    await session.commit()
    await session.refresh(job)


async def update_background_job_progress(
    *,
    session: AsyncSession,
    job: BackgroundJob,
    progress_percent: int,
) -> None:
    if not 0 <= progress_percent <= 100:
        raise ValueError("Background job progress must be between 0 and 100")

    job.progress_percent = progress_percent

    await session.commit()
    await session.refresh(job)


async def set_background_job_event_id(
    *,
    session: AsyncSession,
    job: BackgroundJob,
    event_id: str,
) -> None:
    job.inngest_event_id = event_id

    await session.commit()
    await session.refresh(job)


async def prepare_background_job_dispatch(
    *,
    session: AsyncSession,
    job: BackgroundJob,
) -> uuid.UUID | None:
    dispatch_id = uuid.uuid4()

    statement = (
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job.id,
            BackgroundJob.organization_id == job.organization_id,
            (
                (BackgroundJob.status == BackgroundJobStatus.FAILED)
                | (
                    (BackgroundJob.status == BackgroundJobStatus.QUEUED)
                    & (BackgroundJob.dispatch_id.is_(None))
                )
            ),
        )
        .values(
            dispatch_id=dispatch_id,
            inngest_event_id=None,
            status=BackgroundJobStatus.QUEUED,
            progress_percent=0,
            error_message=None,
            started_at=None,
            completed_at=None,
        )
        .returning(BackgroundJob.dispatch_id)
    )

    try:
        result = await session.execute(statement)
        claimed_dispatch_id = result.scalar_one_or_none()

        await session.commit()
        await session.refresh(job)

        return claimed_dispatch_id
    except Exception:
        await session.rollback()
        raise
