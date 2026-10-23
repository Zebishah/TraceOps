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
from ops_pilot.services.automation_events import (
    dispatch_document_indexing_failed_automation,
)
from ops_pilot.services.background_jobs import (
    get_background_job,
    mark_background_job_failed,
    mark_background_job_processing,
    mark_background_job_succeeded,
    update_background_job_progress,
)
from ops_pilot.services.document_indexing import (
    index_document,
)
from ops_pilot.services.document_processing import (
    get_document,
    process_document,
)

DOCUMENT_PROCESSING_EVENT = "ops_pilot/document.processing.requested"


async def _get_document_job(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
) -> BackgroundJob:
    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=organization_id,
            job_id=job_id,
        )

        if job is None:
            raise RuntimeError("Background job not found")

        if job.job_type != BackgroundJobType.DOCUMENT_PROCESSING:
            raise RuntimeError("Background job type mismatch")

        if job.resource_id != document_id:
            raise RuntimeError("Background job resource mismatch")

        return job


def _validate_current_dispatch(
    *,
    job: BackgroundJob,
    dispatch_id: uuid.UUID,
) -> None:
    if job.dispatch_id != dispatch_id:
        raise RuntimeError("Background job dispatch mismatch")


def _should_ignore_failure(
    *,
    job: BackgroundJob,
    dispatch_id: uuid.UUID,
) -> bool:
    return job.dispatch_id != dispatch_id or job.status == BackgroundJobStatus.SUCCEEDED


async def _mark_job_processing(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
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

        if job.job_type != BackgroundJobType.DOCUMENT_PROCESSING:
            raise RuntimeError("Background job type mismatch")

        if job.resource_id != document_id:
            raise RuntimeError("Background job resource mismatch")

        _validate_current_dispatch(
            job=job,
            dispatch_id=dispatch_id,
        )

        if job.status == BackgroundJobStatus.SUCCEEDED:
            return {
                "already_succeeded": True,
                "progress_percent": 100,
            }

        await mark_background_job_processing(
            session=session,
            job=job,
            progress_percent=10,
        )

        return {
            "already_succeeded": False,
            "progress_percent": 10,
        }


async def _process_document_step(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
) -> dict[str, object]:
    async with async_session_factory() as session:
        document = await process_document(
            session=session,
            organization_id=organization_id,
            document_id=document_id,
        )

        document_status = document.status.value

    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=organization_id,
            job_id=job_id,
        )

        if job is None:
            raise RuntimeError("Background job not found")

        await update_background_job_progress(
            session=session,
            job=job,
            progress_percent=60,
        )

    return {
        "document_id": str(document_id),
        "document_status": document_status,
        "progress_percent": 60,
    }


async def _index_document_step(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
) -> dict[str, object]:
    async with async_session_factory() as session:
        indexed_chunks = await index_document(
            session=session,
            organization_id=organization_id,
            document_id=document_id,
        )

    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=organization_id,
            job_id=job_id,
        )

        if job is None:
            raise RuntimeError("Background job not found")

        await update_background_job_progress(
            session=session,
            job=job,
            progress_percent=90,
        )

    return {
        "document_id": str(document_id),
        "indexed_chunks": indexed_chunks,
        "progress_percent": 90,
    }


async def _mark_job_succeeded(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict[str, object]:
    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=organization_id,
            job_id=job_id,
        )

        if job is None:
            raise RuntimeError("Background job not found")

        await mark_background_job_succeeded(
            session=session,
            job=job,
        )

    return {
        "job_id": str(job_id),
        "status": (BackgroundJobStatus.SUCCEEDED.value),
        "progress_percent": 100,
    }


def _extract_failure_event_data(
    data: Mapping[str, object],
) -> BackgroundJobEventData | None:
    original_event = data.get("event")

    if not isinstance(
        original_event,
        dict,
    ):
        return None

    original_data = original_event.get("data")

    if not isinstance(
        original_data,
        dict,
    ):
        return None

    try:
        return BackgroundJobEventData.model_validate(original_data)
    except ValidationError:
        return None


def _extract_failure_message(
    data: Mapping[str, object],
) -> str:
    error = data.get("error")

    if not isinstance(
        error,
        dict,
    ):
        return "Background document processing failed"

    message = error.get("message")

    if not isinstance(
        message,
        str,
    ):
        return "Background document processing failed"

    return message


async def document_processing_on_failure(
    ctx: inngest.Context,
) -> None:
    data = ctx.event.data

    event_data = _extract_failure_event_data(data)

    if event_data is None:
        return

    error_message = _extract_failure_message(data)

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

            if _should_ignore_failure(
                job=job,
                dispatch_id=event_data.dispatch_id,
            ):
                return {
                    "status": "ignored_stale_failure",
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
        "mark-job-failed",
        mark_failed,
    )

    async def dispatch_indexing_failure() -> dict[str, object]:
        try:
            async with async_session_factory() as session:
                job = await get_background_job(
                    session=session,
                    organization_id=(event_data.organization_id),
                    job_id=event_data.job_id,
                )

                if job is None:
                    return {
                        "dispatched": False,
                        "reason": "job_not_found",
                    }

                if _should_ignore_failure(
                    job=job,
                    dispatch_id=event_data.dispatch_id,
                ):
                    return {
                        "dispatched": False,
                        "reason": "stale_or_completed_dispatch",
                    }

                # 60% means document processing finished
                # and the workflow had reached indexing.
                if job.progress_percent < 60:
                    return {
                        "dispatched": False,
                        "reason": "not_indexing_failure",
                    }

                document = await get_document(
                    session=session,
                    organization_id=(event_data.organization_id),
                    document_id=(event_data.resource_id),
                )

            await dispatch_document_indexing_failed_automation(
                organization_id=(event_data.organization_id),
                document_id=(event_data.resource_id),
                job_id=event_data.job_id,
                filename=document.original_filename,
                error_message=error_message,
            )

        except Exception:
            return {
                "dispatched": False,
                "reason": "automation_failed",
            }

        return {
            "dispatched": True,
        }

    await ctx.step.run(
        "dispatch-indexing-failure-automation",
        dispatch_indexing_failure,
    )


@inngest_client.create_function(
    fn_id="process-document-background",
    name="Process Document",
    trigger=inngest.TriggerEvent(
        event=DOCUMENT_PROCESSING_EVENT,
    ),
    retries=4,
    idempotency="event.data.dispatch_id",
    on_failure=document_processing_on_failure,
)
async def process_document_background(
    ctx: inngest.Context,
) -> dict[str, object]:
    event_data = BackgroundJobEventData.model_validate(ctx.event.data)

    organization_id = event_data.organization_id
    job_id = event_data.job_id
    document_id = event_data.resource_id

    async def mark_processing() -> dict[str, object]:
        return await _mark_job_processing(
            organization_id=organization_id,
            job_id=job_id,
            document_id=document_id,
            dispatch_id=event_data.dispatch_id,
        )

    processing_result = await ctx.step.run(
        "mark-job-processing",
        mark_processing,
    )

    already_succeeded = processing_result.get("already_succeeded")

    if already_succeeded is True:
        return {
            "job_id": str(job_id),
            "document_id": str(document_id),
            "status": (BackgroundJobStatus.SUCCEEDED.value),
            "already_succeeded": True,
        }

    async def process() -> dict[str, object]:
        return await _process_document_step(
            organization_id=organization_id,
            job_id=job_id,
            document_id=document_id,
        )

    await ctx.step.run(
        "process-document",
        process,
    )

    async def index() -> dict[str, object]:
        return await _index_document_step(
            organization_id=organization_id,
            job_id=job_id,
            document_id=document_id,
        )

    index_result = await ctx.step.run(
        "index-document",
        index,
    )

    async def mark_succeeded() -> dict[str, object]:
        return await _mark_job_succeeded(
            organization_id=organization_id,
            job_id=job_id,
        )

    await ctx.step.run(
        "mark-job-succeeded",
        mark_succeeded,
    )

    return {
        "job_id": str(job_id),
        "document_id": str(document_id),
        "status": (BackgroundJobStatus.SUCCEEDED.value),
        "indexed_chunks": index_result["indexed_chunks"],
    }
