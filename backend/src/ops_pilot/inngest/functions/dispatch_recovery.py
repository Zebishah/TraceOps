"""Scheduled recovery of abandoned background job dispatches."""

import inngest

from ops_pilot.inngest.client import inngest_client
from ops_pilot.services.background_dispatch_recovery import (
    recover_abandoned_dispatches,
)


async def run_dispatch_recovery() -> dict[str, int]:
    """Run one recovery sweep and return its counters."""
    result = await recover_abandoned_dispatches()

    if result.failed:
        raise RuntimeError(f"Background dispatch recovery failed for {result.failed} jobs")

    return {
        "candidates": result.candidates,
        "attempted": result.attempted,
        "failed": result.failed,
    }


@inngest_client.create_function(
    fn_id="recover-abandoned-background-dispatches",
    name="Recover Abandoned Background Dispatches",
    trigger=inngest.TriggerCron(
        cron="* * * * *",
    ),
    retries=2,
)
async def recover_background_dispatches(
    ctx: inngest.Context,
) -> dict[str, int]:
    return await ctx.step.run(
        "recover-dispatches",
        run_dispatch_recovery,
    )
