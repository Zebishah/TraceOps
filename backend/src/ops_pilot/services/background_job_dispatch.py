import uuid

import inngest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.inngest.client import inngest_client
from ops_pilot.inngest.functions.document_processing import (
    DOCUMENT_PROCESSING_EVENT,
)
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.schemas.background_jobs import (
    BackgroundJobEventData,
)
from ops_pilot.services.background_jobs import (
    create_background_job,
    prepare_background_job_dispatch,
    set_background_job_event_id,
)
from ops_pilot.services.document_processing import (
    get_document,
)

MEMORY_INDEXING_EVENT = "ops_pilot/memory.indexing.requested"


async def enqueue_document_processing(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
) -> BackgroundJob:
    await get_document(
        session=session,
        organization_id=organization_id,
        document_id=document_id,
    )

    job = await create_background_job(
        session=session,
        organization_id=organization_id,
        created_by_user_id=user_id,
        job_type=BackgroundJobType.DOCUMENT_PROCESSING,
        resource_id=document_id,
        idempotency_key=(f"document-processing:{document_id}"),
    )

    # Active/completed job already exists.
    # Do not enqueue duplicate work.
    if job.status in {
        BackgroundJobStatus.PROCESSING,
        BackgroundJobStatus.SUCCEEDED,
    }:
        return job

    if job.status == BackgroundJobStatus.QUEUED and job.dispatch_id is not None:
        if job.inngest_event_id is not None:
            return job

        dispatch_id = job.dispatch_id
    else:
        dispatch_id = await prepare_background_job_dispatch(
            session=session,
            job=job,
        )

    event_data = BackgroundJobEventData(
        job_id=job.id,
        dispatch_id=dispatch_id,
        organization_id=organization_id,
        resource_id=document_id,
    )

    event_ids = await inngest_client.send(
        inngest.Event(
            id=str(dispatch_id),
            name=DOCUMENT_PROCESSING_EVENT,
            data=event_data.model_dump(
                mode="json",
            ),
        )
    )

    if not event_ids:
        raise RuntimeError("Inngest did not return an event ID")

    await set_background_job_event_id(
        session=session,
        job=job,
        event_id=event_ids[0],
    )

    return job


async def enqueue_memory_indexing(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> BackgroundJob:
    job = await create_background_job(
        session=session,
        organization_id=organization_id,
        created_by_user_id=None,
        job_type=BackgroundJobType.MEMORY_INDEXING,
        resource_id=incident_id,
        idempotency_key=(f"memory-indexing:{incident_id}"),
    )

    if job.status in {
        BackgroundJobStatus.PROCESSING,
        BackgroundJobStatus.SUCCEEDED,
    }:
        return job

    if job.status == BackgroundJobStatus.QUEUED and job.dispatch_id is not None:
        if job.inngest_event_id is not None:
            return job

        dispatch_id = job.dispatch_id

    else:
        dispatch_id = await prepare_background_job_dispatch(
            session=session,
            job=job,
        )

    event_data = BackgroundJobEventData(
        job_id=job.id,
        dispatch_id=dispatch_id,
        organization_id=organization_id,
        resource_id=incident_id,
    )

    event_ids = await inngest_client.send(
        inngest.Event(
            id=str(dispatch_id),
            name=MEMORY_INDEXING_EVENT,
            data=event_data.model_dump(
                mode="json",
            ),
        )
    )

    if not event_ids:
        raise RuntimeError("Inngest did not return an event ID")

    await set_background_job_event_id(
        session=session,
        job=job,
        event_id=event_ids[0],
    )

    return job
