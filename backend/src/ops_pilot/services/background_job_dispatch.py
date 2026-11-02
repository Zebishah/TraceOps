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
from ops_pilot.models.document import DocumentStatus
from ops_pilot.schemas.background_jobs import (
    BackgroundJobEventData,
)
from ops_pilot.services.background_jobs import (
    claim_background_job_send_lease,
    create_background_job,
    prepare_background_job_dispatch,
    prepare_document_reindex_dispatch,
    record_background_job_send_success,
)
from ops_pilot.services.document_processing import (
    get_document,
)

MEMORY_INDEXING_EVENT = "ops_pilot/memory.indexing.requested"
INCIDENT_ANALYSIS_EVENT = "ops_pilot/incident.analysis.requested"


async def _send_background_job_event(
    *,
    session: AsyncSession,
    job: BackgroundJob,
    dispatch_id: uuid.UUID,
    event_name: str,
    organization_id: uuid.UUID,
    resource_id: uuid.UUID,
) -> None:
    lease_token = await claim_background_job_send_lease(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
    )

    if lease_token is None:
        # Another sender owns the unexpired lease,
        # the job has already started or finished,
        # or the event was already acknowledged.
        return

    event_data = BackgroundJobEventData(
        job_id=job.id,
        dispatch_id=dispatch_id,
        organization_id=organization_id,
        resource_id=resource_id,
    )

    event_ids = await inngest_client.send(
        inngest.Event(
            id=str(dispatch_id),
            name=event_name,
            data=event_data.model_dump(mode="json"),
        )
    )

    if not event_ids:
        raise RuntimeError("Inngest did not return an event ID")

    await record_background_job_send_success(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        lease_token=lease_token,
        event_id=event_ids[0],
    )


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
        idempotency_key=f"document-processing:{document_id}",
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
        claimed = await prepare_background_job_dispatch(
            session=session,
            job=job,
        )

        if claimed is None:
            return job

        dispatch_id = claimed

    await _send_background_job_event(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        event_name=DOCUMENT_PROCESSING_EVENT,
        organization_id=organization_id,
        resource_id=document_id,
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
        idempotency_key=f"memory-indexing:{incident_id}",
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
        claimed = await prepare_background_job_dispatch(
            session=session,
            job=job,
        )

        if claimed is None:
            return job

        dispatch_id = claimed

    await _send_background_job_event(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        event_name=MEMORY_INDEXING_EVENT,
        organization_id=organization_id,
        resource_id=incident_id,
    )

    return job


async def enqueue_document_reindex(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
) -> BackgroundJob:
    """Request document indexing through a fenced dispatch.

    Reuses the existing document job so that concurrent
    reindex requests cannot create independent active
    jobs for the same document.
    """
    document = await get_document(
        session=session,
        organization_id=organization_id,
        document_id=document_id,
    )

    # A document that has never been processed must go
    # through the normal extraction + indexing workflow.
    if document.status != DocumentStatus.READY or document.extracted_text_key is None:
        return await enqueue_document_processing(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            document_id=document_id,
        )

    job = await create_background_job(
        session=session,
        organization_id=organization_id,
        created_by_user_id=user_id,
        job_type=BackgroundJobType.DOCUMENT_PROCESSING,
        resource_id=document_id,
        idempotency_key=f"document-processing:{document_id}",
    )

    # Another execution is already active. Return it;
    # do not replace its dispatch.
    if job.status == BackgroundJobStatus.PROCESSING:
        return job

    if job.status == BackgroundJobStatus.QUEUED:
        if job.dispatch_id is not None:
            if job.inngest_event_id is not None:
                return job

            dispatch_id = job.dispatch_id
        else:
            claimed = await prepare_background_job_dispatch(
                session=session,
                job=job,
            )

            if claimed is None:
                return job

            dispatch_id = claimed

    elif job.status == BackgroundJobStatus.SUCCEEDED:
        claimed = await prepare_document_reindex_dispatch(
            session=session,
            job=job,
            document_id=document_id,
        )

        if claimed is None:
            return job

        dispatch_id = claimed

    elif job.status == BackgroundJobStatus.FAILED:
        claimed = await prepare_background_job_dispatch(
            session=session,
            job=job,
        )

        if claimed is None:
            return job

        dispatch_id = claimed

    else:
        raise RuntimeError("Unexpected document job status")

    await _send_background_job_event(
        session=session,
        job=job,
        dispatch_id=dispatch_id,
        event_name=DOCUMENT_PROCESSING_EVENT,
        organization_id=organization_id,
        resource_id=document_id,
    )

    return job
