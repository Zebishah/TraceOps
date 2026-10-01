import uuid

from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.schemas.incidents import (
    IncidentInvestigationResponse,
)
from ops_pilot.workflows.incident.checkpointing import (
    open_incident_checkpointer,
)
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)
from ops_pilot.workflows.incident.state import (
    IncidentGraphContext,
)


async def investigate_incident(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    workflow_thread_id: str | None = None,
) -> IncidentInvestigationResponse:
    thread_id = workflow_thread_id or str(uuid.uuid4())

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    async with open_incident_checkpointer() as checkpointer:
        graph = build_incident_investigation_graph(
            checkpointer=checkpointer,
        )

        result = await graph.ainvoke(
            {
                "organization_id": organization_id,
                "incident_id": incident_id,
                "workflow_thread_id": thread_id,
            },
            config=config,
            context=IncidentGraphContext(
                session=session,
            ),
        )

    try:
        return IncidentInvestigationResponse.model_validate(
            result,
        )
    except ValidationError as exc:
        raise RuntimeError(
            "Incident investigation graph returned an incomplete result",
        ) from exc
