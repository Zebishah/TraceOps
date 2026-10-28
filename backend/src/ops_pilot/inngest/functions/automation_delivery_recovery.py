"""Scheduled recovery of failed n8n automation deliveries."""

import inngest

from ops_pilot.inngest.client import inngest_client
from ops_pilot.services.automation_outbox import (
    recover_automation_deliveries,
)


@inngest_client.create_function(
    fn_id="recover-automation-deliveries",
    name="Recover Automation Deliveries",
    trigger=inngest.TriggerCron(
        cron="* * * * *",
    ),
    retries=2,
)
async def recover_automation_deliveries_background(
    ctx: inngest.Context,
) -> dict[str, int]:
    return await ctx.step.run(
        "recover-automation-outbox",
        recover_automation_deliveries,
    )
