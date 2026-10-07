import uuid
from collections.abc import Mapping

import inngest
from pydantic import ValidationError

from ops_pilot.db.session import async_session_factory
from ops_pilot.inngest.client import inngest_client
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.schemas.background_jobs import (
    BackgroundJobEventData,
)
from ops_pilot.services.background_job_dispatch import (
    MEMORY_INDEXING_EVENT,
)
from ops_pilot.services.background_jobs import (
    get_background_job,
    mark_background_job_failed,
    mark_background_job_processing,
    mark_background_job_succeeded,
)
from ops_pilot.services.incident_memory_indexing import (
    index_incident_memory,
)


def _validate_memory_job(
    *,
    job: BackgroundJob,
    incident_id: uuid.UUID,
    dispatch_id: uuid.UUID,
) -> None:
    if job.job_type != BackgroundJobType.MEMORY_INDEXING:
        raise RuntimeError("Background job type mismatch")

    if job.resource_id != incident_id:
        raise RuntimeError("Background job resource mismatch")

    if job.dispatch_id != dispatch_id:
        raise RuntimeError("Background job dispatch mismatch")


async def _mark_memory_job_processing(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    incident_id: uuid.UUID,
    dispatch_id: uuid.UUID,
) -> dict[str, object]:
    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=organization_id,
            job_id=job_id,
        )

        if job is None:
            raise RuntimeError("Background job not found")

        _validate_memory_job(
            job=job,
            incident_id=incident_id,
            dispatch_id=dispatch_id,
        )

        if job.status == BackgroundJobStatus.SUCCEEDED:
            return {
                "already_succeeded": True,
            }

        await mark_background_job_processing(
            session=session,
            job=job,
            progress_percent=10,
        )

        return {
            "already_succeeded": False,
        }


async def _index_memory_step(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    incident_id: uuid.UUID,
    dispatch_id: uuid.UUID,
) -> dict[str, object]:
    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=organization_id,
            job_id=job_id,
        )

        if job is None:
            raise RuntimeError("Background job not found")

        _validate_memory_job(
            job=job,
            incident_id=incident_id,
            dispatch_id=dispatch_id,
        )

    async with async_session_factory() as session:
        indexed = await index_incident_memory(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )

    return {
        "indexed_memories": indexed,
    }


async def _mark_memory_job_succeeded(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    incident_id: uuid.UUID,
    dispatch_id: uuid.UUID,
) -> dict[str, object]:
    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=organization_id,
            job_id=job_id,
        )

        if job is None:
            raise RuntimeError("Background job not found")

        _validate_memory_job(
            job=job,
            incident_id=incident_id,
            dispatch_id=dispatch_id,
        )

        await mark_background_job_succeeded(
            session=session,
            job=job,
        )

    return {
        "status": (BackgroundJobStatus.SUCCEEDED.value),
    }


def _extract_failure_event_data(
    data: Mapping[str, object],
) -> BackgroundJobEventData | None:
    original_event = data.get("event")

    if not isinstance(
        original_event,
        Mapping,
    ):
        return None

    original_data = original_event.get("data")

    if not isinstance(
        original_data,
        Mapping,
    ):
        return None

    try:
        return BackgroundJobEventData.model_validate(dict(original_data))
    except ValidationError:
        return None


def _extract_failure_message(
    data: Mapping[str, object],
) -> str:
    error = data.get("error")

    if not isinstance(
        error,
        Mapping,
    ):
        return "Background memory indexing failed"

    message = error.get("message")

    if not isinstance(
        message,
        str,
    ):
        return "Background memory indexing failed"

    return message


async def memory_indexing_on_failure(
    ctx: inngest.Context,
) -> None:
    event_data = _extract_failure_event_data(ctx.event.data)

    if event_data is None:
        return

    error_message = _extract_failure_message(ctx.event.data)

    async def mark_failed() -> dict[str, str]:
        async with async_session_factory() as session:
            job = await get_background_job(
                session=session,
                organization_id=(event_data.organization_id),
                job_id=event_data.job_id,
            )

            if job is None:
                return {
                    "status": "job_not_found",
                }

            # Do not let an old failed execution
            # overwrite a newer retry.
            if job.dispatch_id != event_data.dispatch_id:
                return {
                    "status": "stale_dispatch",
                }

            await mark_background_job_failed(
                session=session,
                job=job,
                error_message=error_message,
            )

        return {
            "status": (BackgroundJobStatus.FAILED.value),
        }

    await ctx.step.run(
        "mark-memory-job-failed",
        mark_failed,
    )


@inngest_client.create_function(
    fn_id="index-incident-memory-background",
    name="Index Incident Memory",
    trigger=inngest.TriggerEvent(
        event=MEMORY_INDEXING_EVENT,
    ),
    retries=4,
    idempotency="event.data.dispatch_id",
    on_failure=memory_indexing_on_failure,
)
async def index_incident_memory_background(
    ctx: inngest.Context,
) -> dict[str, object]:
    event_data = BackgroundJobEventData.model_validate(ctx.event.data)

    organization_id = event_data.organization_id
    job_id = event_data.job_id
    incident_id = event_data.resource_id
    dispatch_id = event_data.dispatch_id

    async def mark_processing() -> dict[str, object]:
        return await _mark_memory_job_processing(
            organization_id=organization_id,
            job_id=job_id,
            incident_id=incident_id,
            dispatch_id=dispatch_id,
        )

    processing_result = await ctx.step.run(
        "mark-memory-job-processing",
        mark_processing,
    )

    if processing_result.get("already_succeeded") is True:
        return {
            "job_id": str(job_id),
            "status": (BackgroundJobStatus.SUCCEEDED.value),
            "already_succeeded": True,
        }

    async def index_memory() -> dict[str, object]:
        return await _index_memory_step(
            organization_id=organization_id,
            job_id=job_id,
            incident_id=incident_id,
            dispatch_id=dispatch_id,
        )

    index_result = await ctx.step.run(
        "index-incident-memory",
        index_memory,
    )

    async def mark_succeeded() -> dict[str, object]:
        return await _mark_memory_job_succeeded(
            organization_id=organization_id,
            job_id=job_id,
            incident_id=incident_id,
            dispatch_id=dispatch_id,
        )

    await ctx.step.run(
        "mark-memory-job-succeeded",
        mark_succeeded,
    )

    return {
        "job_id": str(job_id),
        "incident_id": str(incident_id),
        "status": (BackgroundJobStatus.SUCCEEDED.value),
        "indexed_memories": index_result["indexed_memories"],
    }
