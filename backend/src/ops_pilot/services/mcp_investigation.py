import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.schemas.incidents import (
    IncidentInvestigationResponse,
)
from ops_pilot.services.incident_investigation import (
    investigate_incident,
)
from ops_pilot.services.mcp_incidents import (
    get_incident_detail,
)


async def investigate_incident_for_mcp(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> IncidentInvestigationResponse | None:
    incident = await get_incident_detail(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    if incident is None:
        return None

    return await investigate_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )
