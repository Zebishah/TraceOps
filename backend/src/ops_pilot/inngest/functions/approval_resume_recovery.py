"""Scheduled processing and reconciliation of approval resume jobs."""

import logging

import inngest

from ops_pilot.core.config import get_settings
from ops_pilot.inngest.client import inngest_client
from ops_pilot.services.approval_recovery_alerts import (
    evaluate_recovery_alerts,
)
from ops_pilot.services.approval_recovery_health import (
    get_approval_recovery_health,
)
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

    health = await get_approval_recovery_health()

    settings = get_settings()

    alerts = evaluate_recovery_alerts(
        health=health,
        quarantine_count_threshold=(settings.approval_recovery_quarantine_alert_count),
        quarantine_age_threshold_seconds=(settings.approval_recovery_quarantine_age_alert_seconds),
        processing_count_threshold=(settings.approval_recovery_processing_alert_count),
    )

    for alert in alerts:
        logger.error(
            "approval_recovery_threshold_breached",
            extra={
                "alert_code": alert.code,
                "alert_severity": alert.severity,
                "alert_actual": alert.actual,
                "alert_threshold": alert.threshold,
            },
        )

    if health.quarantined > 0:
        logger.error(
            "approval_recovery_quarantined_backlog",
            extra=health.as_dict(),
        )

    counters: dict[str, int] = {
        "claimed": result.claimed,
        "completed": result.completed,
        "failed": result.failed,
        "quarantined": quarantined,
        "reconciled": reconciliation.completed,
        "unresolved": reconciliation.unresolved,
        "quarantined_backlog": health.quarantined,
        "pending_backlog": health.pending,
        "processing_backlog": health.processing,
        "retryable_failed_backlog": health.retryable_failed,
        "oldest_quarantine_age_seconds": (health.oldest_quarantine_age_seconds or 0),
    }

    logger.info(
        "approval_resume_recovery_sweep",
        extra=counters,
    )

    if result.failed:
        raise RuntimeError(f"Approval resume sweep failed for {result.failed} jobs")

    return counters


async def execute_approval_recovery(
    ctx: inngest.Context,
) -> dict[str, int]:
    """Enforce recovery execution gates before any sweep."""

    settings = get_settings()
    environment = settings.environment.lower()

    if not settings.approval_recovery_execution_enabled:
        logger.warning(
            "approval_recovery_execution_disabled",
            extra={"environment": environment},
        )
        return {"skipped": 1}

    if environment == "staging":
        if not settings.enable_approval_resume_cron:
            logger.warning("approval_recovery_staging_registration_disabled")
            return {"skipped": 1}

    elif environment == "production":
        if not settings.enable_production_approval_recovery:
            logger.warning("approval_recovery_production_registration_disabled")
            return {"skipped": 1}

    else:
        logger.warning(
            "approval_recovery_unsupported_environment",
            extra={"environment": environment},
        )
        return {"skipped": 1}

    return await ctx.step.run(
        "recover-approval-resumes",
        run_approval_resume_recovery,
    )


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
    """Inngest entry point for gated approval recovery."""
    return await execute_approval_recovery(ctx)
