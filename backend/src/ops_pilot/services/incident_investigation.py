import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.schemas.incidents import IncidentInvestigationResponse
from ops_pilot.workflows.incident.graph import (
    incident_investigation_graph,
)
from ops_pilot.workflows.incident.state import IncidentGraphContext


async def investigate_incident(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> IncidentInvestigationResponse:
    result = await incident_investigation_graph.ainvoke(
        {
            "organization_id": organization_id,
            "incident_id": incident_id,
        },
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
