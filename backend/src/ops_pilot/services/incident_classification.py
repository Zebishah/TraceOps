import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.ai.incident_classifier import classify_incident
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.schemas.incident_classification import IncidentClassification
from ops_pilot.services.incident_resolution import IncidentResolutionConflict
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

    if incident.status == IncidentStatus.RESOLVED:
        raise IncidentResolutionConflict("Resolved incidents cannot be reclassified")

    title = incident.title
    description = incident.description

    # Do not hold a database transaction during the AI call.
    await session.rollback()

    classification = await classify_incident(
        title=title,
        description=description,
    )

    # Lock the incident before updating it.
    result = await session.execute(
        select(Incident)
        .where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    locked_incident = result.scalar_one_or_none()

    if locked_incident is None:
        await session.rollback()
        raise IncidentResolutionConflict("Incident no longer exists")

    # Recheck after the AI call: a reviewer might
    # have resolved the incident while AI was running.
    current_status: IncidentStatus = IncidentStatus(locked_incident.status.value)

    if current_status is IncidentStatus.RESOLVED:
        await session.rollback()
        raise IncidentResolutionConflict("Incident was resolved during classification")

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
