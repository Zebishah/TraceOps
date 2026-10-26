"""Scheduled processing and reconciliation of approval resume jobs."""

import logging

import inngest

from ops_pilot.inngest.client import inngest_client
from ops_pilot.services.approval_resume_processor import (
    run_approval_resume_sweep,
)
from ops_pilot.services.approval_resume_reconciliation import (
    reconcile_quarantined_jobs,
)
from ops_pilot.services.approval_resume_recovery import (
    quarantine_expired_resume_jobs,
)

logger = logging.getLogger(__name__)


async def run_approval_resume_recovery() -> dict[str, int]:
    """Process pending approvals and inspect uncertain outcomes."""

    quarantined = await quarantine_expired_resume_jobs()

    reconciliation = await reconcile_quarantined_jobs()

    result = await run_approval_resume_sweep()

    counters: dict[str, int] = {
        "claimed": result.claimed,
        "completed": result.completed,
        "failed": result.failed,
        "quarantined": quarantined,
        "reconciled": reconciliation.completed,
        "unresolved": reconciliation.unresolved,
    }

    logger.info(
        "approval_resume_recovery_sweep",
        extra=counters,
    )

    if result.failed:
        raise RuntimeError(f"Approval resume sweep failed for {result.failed} jobs")

    return counters


@inngest_client.create_function(
    fn_id="recover-approval-resume-jobs",
    name="Recover Approval Resume Jobs",
    trigger=inngest.TriggerCron(
        cron="*/10 * * * *",
    ),
    retries=1,
)
async def recover_approval_resume_jobs(
    ctx: inngest.Context,
) -> dict[str, int]:
    return await ctx.step.run(
        "recover-approval-resumes",
        run_approval_resume_recovery,
    )
