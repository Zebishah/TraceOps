import inngest

from ops_pilot.inngest.client import inngest_client


@inngest_client.create_function(
    fn_id="background-health-check",
    trigger=inngest.TriggerEvent(
        event="ops_pilot/background.health.requested",
    ),
)
async def background_health_check(
    ctx: inngest.Context,
) -> dict[str, str]:
    value = str(
        ctx.event.data.get(
            "value",
            "hello",
        )
    )

    return {
        "result": f"processed:{value}",
    }
