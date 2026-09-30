import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    CustomerNotFoundError,
    IncidentNotFoundError,
)
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident
from ops_pilot.schemas.incidents import IncidentCreateRequest


async def create_incident(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: IncidentCreateRequest,
) -> Incident:

    if payload.subject_customer_id is not None:
        result = await session.execute(
            select(Customer.id).where(
                Customer.id == payload.subject_customer_id,
                Customer.organization_id == organization_id,
            )
        )

        if result.scalar_one_or_none() is None:
            raise CustomerNotFoundError
    incident = Incident(
        organization_id=organization_id,
        created_by_user_id=user_id,
        title=payload.title,
        description=payload.description,
        subject_customer_id=payload.subject_customer_id,
    )

    session.add(incident)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(incident)

    return incident


async def list_incidents(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> list[Incident]:
    result = await session.execute(
        select(Incident)
        .where(
            Incident.organization_id == organization_id,
        )
        .order_by(
            Incident.created_at.desc(),
        )
    )

    return list(result.scalars().all())


async def get_incident(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> Incident:
    result = await session.execute(
        select(Incident).where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
    )

    incident = result.scalar_one_or_none()

    if incident is None:
        raise IncidentNotFoundError

    return incident
