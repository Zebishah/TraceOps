import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.ai.incident_classifier import classify_incident
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.schemas.incident_classification import IncidentClassification
from ops_pilot.services.incidents import get_incident


async def classify_stored_incident(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> tuple[Incident, IncidentClassification]:
    incident = await get_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    title = incident.title
    description = incident.description

    # We do not need PostgreSQL while waiting for the AI provider.
    await session.rollback()

    classification = await classify_incident(
        title=title,
        description=description,
    )

    # Fetch a fresh ORM object before writing.
    incident = await get_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    incident.category = classification.category.value
    incident.priority = classification.priority
    incident.status = IncidentStatus.INVESTIGATING

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(incident)

    return incident, classification
