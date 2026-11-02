import uuid
from collections.abc import Mapping

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.db.session import async_session_factory
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.schemas.background_jobs import BackgroundJobEventData
from ops_pilot.schemas.incidents import IncidentInvestigationResponse
from ops_pilot.services.background_job_dispatch import (
    INCIDENT_ANALYSIS_EVENT,
    _send_background_job_event,
)
from ops_pilot.services.background_jobs import (
    create_background_job,
    get_background_job,
    prepare_background_job_dispatch,
    update_job_for_dispatch,
)
from ops_pilot.services.incident_resolution import IncidentResolutionConflict
from ops_pilot.services.incidents import get_incident, invalidate_incident_cache
from ops_pilot.workflows.incident.checkpointing import open_incident_checkpointer
from ops_pilot.workflows.incident.graph import build_incident_investigation_graph
from ops_pilot.workflows.incident.state import IncidentGraphContext


def investigation_thread_id(job_id: uuid.UUID) -> str:
    return f"incident-analysis:{job_id}"


def validate_checkpoint_identity(
    *,
    values: Mapping[str, object],
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> None:
    expected = {
        "organization_id": organization_id,
        "incident_id": incident_id,
    }

    for field, expected_id in expected.items():
        try:
            actual_id = uuid.UUID(str(values.get(field)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError(f"Investigation checkpoint has invalid {field}") from exc

        if actual_id != expected_id:
            raise RuntimeError(f"Investigation checkpoint {field} mismatch")


async def enqueue_incident_analysis(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    user_id: uuid.UUID,
) -> BackgroundJob:
    incident = await get_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    # Repeated requests return the same job for this incident.
    # This batch does not automatically restart failed investigations.
    existing = await session.execute(
        select(BackgroundJob).where(
            BackgroundJob.organization_id == organization_id,
            BackgroundJob.idempotency_key == f"incident-analysis:{incident_id}",
        )
    )
    job = existing.scalar_one_or_none()

    if job is None:
        if incident.status not in {
            IncidentStatus.NEW,
            IncidentStatus.INVESTIGATING,
        }:
            raise IncidentResolutionConflict(
                "Incident cannot start an investigation in its current state"
            )

        job = await create_background_job(
            session=session,
            organization_id=organization_id,
            created_by_user_id=user_id,
            job_type=BackgroundJobType.INCIDENT_ANALYSIS,
            resource_id=incident_id,
            idempotency_key=f"incident-analysis:{incident_id}",
        )

    if job.job_type != BackgroundJobType.INCIDENT_ANALYSIS or job.resource_id != incident_id:
        raise RuntimeError("Investigation job identity mismatch")

    if job.status != BackgroundJobStatus.QUEUED:
        return job

    if job.dispatch_id is None:
        dispatch_id = await prepare_background_job_dispatch(
            session=session,
            job=job,
        )
        if dispatch_id is None:
            return job
    else:
        dispatch_id = job.dispatch_id

    if job.inngest_event_id is None:
        await _send_background_job_event(
            session=session,
            job=job,
            dispatch_id=dispatch_id,
            event_name=INCIDENT_ANALYSIS_EVENT,
            organization_id=organization_id,
            resource_id=incident_id,
        )

    return job


async def run_incident_analysis(
    data: BackgroundJobEventData,
) -> dict[str, str]:
    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=data.organization_id,
            job_id=data.job_id,
        )

        if job is None:
            raise RuntimeError("Investigation job not found")

        if (
            job.job_type != BackgroundJobType.INCIDENT_ANALYSIS
            or job.resource_id != data.resource_id
            or job.dispatch_id != data.dispatch_id
        ):
            raise RuntimeError("Investigation dispatch mismatch")

        if job.status == BackgroundJobStatus.SUCCEEDED:
            return {"job_id": str(job.id), "status": "succeeded"}

        if job.status == BackgroundJobStatus.FAILED:
            raise RuntimeError("Failed investigation requires operator review")

        updated = await update_job_for_dispatch(
            session=session,
            job=job,
            dispatch_id=data.dispatch_id,
            status=BackgroundJobStatus.PROCESSING,
            progress_percent=10,
        )

        if not updated:
            raise RuntimeError("Investigation dispatch is no longer active")

    config: RunnableConfig = {
        "configurable": {
            "thread_id": investigation_thread_id(data.job_id),
        }
    }

    async with open_incident_checkpointer() as checkpointer:
        graph = build_incident_investigation_graph(
            checkpointer=checkpointer,
        )
        snapshot = await graph.aget_state(config)

        async with async_session_factory() as session:
            if snapshot.values:
                validate_checkpoint_identity(
                    values=snapshot.values,
                    organization_id=data.organization_id,
                    incident_id=data.resource_id,
                )

                interrupted = any(bool(task.interrupts) for task in snapshot.tasks)

                if interrupted or not snapshot.next:
                    # A human approval pause is a successful investigation.
                    # This worker must never submit an approval decision.
                    result = snapshot.values
                else:
                    # Continue persisted work instead of starting over.
                    result = await graph.ainvoke(
                        None,
                        config=config,
                        context=IncidentGraphContext(session=session),
                    )
            else:
                result = await graph.ainvoke(
                    {
                        "organization_id": data.organization_id,
                        "incident_id": data.resource_id,
                        "workflow_thread_id": investigation_thread_id(data.job_id),
                    },
                    config=config,
                    context=IncidentGraphContext(session=session),
                )

            IncidentInvestigationResponse.model_validate(result)

    await invalidate_incident_cache(
        organization_id=data.organization_id,
        incident_id=data.resource_id,
    )

    async with async_session_factory() as session:
        job = await get_background_job(
            session=session,
            organization_id=data.organization_id,
            job_id=data.job_id,
        )
        if job is None:
            raise RuntimeError("Investigation job disappeared")

        updated = await update_job_for_dispatch(
            session=session,
            job=job,
            dispatch_id=data.dispatch_id,
            status=BackgroundJobStatus.SUCCEEDED,
            progress_percent=100,
        )
        if not updated:
            raise RuntimeError("Investigation completion was not recorded")

    return {"job_id": str(data.job_id), "status": "succeeded"}


async def get_incident_analysis_result(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    job_id: uuid.UUID,
) -> IncidentInvestigationResponse:
    config: RunnableConfig = {
        "configurable": {
            "thread_id": investigation_thread_id(job_id),
        }
    }

    async with open_incident_checkpointer() as checkpointer:
        graph = build_incident_investigation_graph(
            checkpointer=checkpointer,
        )
        snapshot = await graph.aget_state(config)

        validate_checkpoint_identity(
            values=snapshot.values,
            organization_id=organization_id,
            incident_id=incident_id,
        )

        return IncidentInvestigationResponse.model_validate(
            snapshot.values,
        )
