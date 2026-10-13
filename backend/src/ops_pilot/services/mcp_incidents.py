import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.schemas.mcp_incidents import (
    MCPIncidentDetail,
    MCPIncidentSummary,
)


async def list_open_incidents(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    limit: int = 20,
) -> list[MCPIncidentSummary]:
    result = await session.execute(
        select(Incident)
        .where(
            Incident.organization_id == organization_id,
            Incident.status.in_(
                [
                    IncidentStatus.NEW,
                    IncidentStatus.INVESTIGATING,
                    IncidentStatus.AWAITING_APPROVAL,
                ]
            ),
        )
        .order_by(
            Incident.created_at.desc(),
        )
        .limit(limit)
    )

    incidents = result.scalars().all()

    return [
        MCPIncidentSummary.model_validate(
            incident,
            from_attributes=True,
        )
        for incident in incidents
    ]


async def search_incidents(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    query: str,
    limit: int = 20,
) -> list[MCPIncidentSummary]:
    normalized_query = query.strip()

    if not normalized_query:
        return []

    search_pattern = f"%{normalized_query}%"

    result = await session.execute(
        select(Incident)
        .where(
            Incident.organization_id == organization_id,
            or_(
                Incident.title.ilike(search_pattern),
                Incident.description.ilike(search_pattern),
                Incident.category.ilike(search_pattern),
            ),
        )
        .order_by(
            Incident.created_at.desc(),
        )
        .limit(limit)
    )

    incidents = result.scalars().all()

    return [
        MCPIncidentSummary.model_validate(
            incident,
            from_attributes=True,
        )
        for incident in incidents
    ]


async def get_incident_detail(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> MCPIncidentDetail | None:
    result = await session.execute(
        select(Incident).where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
    )

    incident = result.scalar_one_or_none()

    if incident is None:
        return None

    return MCPIncidentDetail.model_validate(
        incident,
        from_attributes=True,
    )
