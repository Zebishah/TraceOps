import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    IncidentMemoryInvalidIncidentError,
    IncidentMemoryNotReadyError,
    IncidentNotFoundError,
)
from ops_pilot.models.incident import (
    Incident,
    IncidentStatus,
)
from ops_pilot.models.incident_memory import IncidentMemory
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryCreate,
)


async def create_or_get_incident_memory(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    payload: IncidentMemoryCreate,
) -> IncidentMemory:
    existing_result = await session.execute(
        select(IncidentMemory).where(
            IncidentMemory.organization_id == organization_id,
            IncidentMemory.incident_id == incident_id,
        )
    )

    existing = existing_result.scalar_one_or_none()

    if existing is not None:
        return existing

    incident_result = await session.execute(
        select(Incident).where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
    )

    incident = incident_result.scalar_one_or_none()

    if incident is None:
        raise IncidentNotFoundError

    if incident.status != IncidentStatus.RESOLVED:
        raise IncidentMemoryNotReadyError

    if incident.category is None:
        raise IncidentMemoryInvalidIncidentError

    memory = IncidentMemory(
        organization_id=organization_id,
        incident_id=incident.id,
        subject_customer_id=incident.subject_customer_id,
        category=incident.category,
        summary=payload.summary,
        resolution=payload.resolution,
    )

    session.add(memory)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(memory)

    return memory


async def get_incident_memory(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> IncidentMemory | None:
    result = await session.execute(
        select(IncidentMemory).where(
            IncidentMemory.organization_id == organization_id,
            IncidentMemory.incident_id == incident_id,
        )
    )

    return result.scalar_one_or_none()
