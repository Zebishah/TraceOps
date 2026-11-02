import inngest

from ops_pilot.db.session import async_session_factory
from ops_pilot.inngest.client import inngest_client
from ops_pilot.models.background_job import (
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.schemas.background_jobs import BackgroundJobEventData
from ops_pilot.services.background_job_dispatch import INCIDENT_ANALYSIS_EVENT
from ops_pilot.services.background_jobs import (
    get_background_job,
    update_job_for_dispatch,
)
from ops_pilot.services.incident_background import run_incident_analysis


async def incident_analysis_on_failure(
    ctx: inngest.Context,
) -> None:
    original_event = ctx.event.data.get("event")
    if not isinstance(original_event, dict):
        return

    original_data = original_event.get("data")
    if not isinstance(original_data, dict):
        return

    data = BackgroundJobEventData.model_validate(original_data)

    async def mark_failed() -> dict[str, bool]:
        async with async_session_factory() as session:
            job = await get_background_job(
                session=session,
                organization_id=data.organization_id,
                job_id=data.job_id,
            )

            if job is None:
                return {"updated": False}

            if (
                job.job_type != BackgroundJobType.INCIDENT_ANALYSIS
                or job.resource_id != data.resource_id
                or job.dispatch_id != data.dispatch_id
            ):
                return {"updated": False}

            updated = await update_job_for_dispatch(
                session=session,
                job=job,
                dispatch_id=data.dispatch_id,
                status=BackgroundJobStatus.FAILED,
                progress_percent=job.progress_percent,
                error_message=(
                    "Investigation failed after retries. Review the Inngest run before retrying."
                ),
            )

        return {"updated": updated}

    await ctx.step.run("mark-investigation-failed", mark_failed)


@inngest_client.create_function(
    fn_id="investigate-incident-background",
    name="Investigate Incident",
    trigger=inngest.TriggerEvent(event=INCIDENT_ANALYSIS_EVENT),
    retries=2,
    idempotency="event.data.dispatch_id",
    concurrency=[
        inngest.Concurrency(limit=1),
    ],
    on_failure=incident_analysis_on_failure,
)
async def investigate_incident_background(
    ctx: inngest.Context,
) -> dict[str, str]:
    data = BackgroundJobEventData.model_validate(ctx.event.data)

    async def investigate() -> dict[str, str]:
        return await run_incident_analysis(data)

    return await ctx.step.run(
        "investigate-from-checkpoint",
        investigate,
    )
