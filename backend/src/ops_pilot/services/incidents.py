import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.cache.service import (
    delete_incident_cache,
    get_incident_cache,
    set_incident_cache,
)
from ops_pilot.core.exceptions import (
    CustomerNotFoundError,
    IncidentNotFoundError,
)
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident
from ops_pilot.schemas.incidents import (
    IncidentCreateRequest,
    IncidentResponse,
)


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
        subject_customer_id=(payload.subject_customer_id),
    )

    session.add(
        incident,
    )

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await session.refresh(
        incident,
    )

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


async def get_incident_response_cached(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> IncidentResponse:
    try:
        cached = await get_incident_cache(
            organization_id=organization_id,
            incident_id=incident_id,
        )
    except Exception:
        # Redis is an optimization.
        # A Redis problem must not break
        # normal PostgreSQL incident reads.
        cached = None

    if cached is not None:
        try:
            return IncidentResponse.model_validate(
                cached,
            )
        except Exception:
            # Invalid/stale cache structure should
            # never break the request.
            try:
                await delete_incident_cache(
                    organization_id=organization_id,
                    incident_id=incident_id,
                )
            except Exception:
                pass

    incident = await get_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    response = IncidentResponse.model_validate(
        incident,
    )

    try:
        await set_incident_cache(
            organization_id=organization_id,
            incident_id=incident_id,
            value=response.model_dump(
                mode="json",
            ),
        )
    except Exception:
        # PostgreSQL succeeded.
        # Redis caching failure is non-critical.
        pass

    return response


async def invalidate_incident_cache(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> None:
    try:
        await delete_incident_cache(
            organization_id=organization_id,
            incident_id=incident_id,
        )
    except Exception:
        # Cache invalidation failure should not
        # fail the real business operation.
        pass
