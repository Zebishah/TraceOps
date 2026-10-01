import asyncio

from ops_pilot.workflows.incident.checkpointing import (
    setup_incident_checkpointer,
)


async def main() -> None:
    await setup_incident_checkpointer()

    print("LangGraph PostgreSQL checkpoint tables are ready.")


if __name__ == "__main__":
    asyncio.run(main())
