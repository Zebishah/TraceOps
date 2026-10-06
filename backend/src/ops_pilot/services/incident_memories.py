import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.ai.incident_memory_writer import (
    generate_incident_memory,
)
from ops_pilot.core.exceptions import (
    IncidentMemoryInvalidIncidentError,
    IncidentMemoryNotReadyError,
    IncidentNotFoundError,
)
from ops_pilot.models.incident import (
    Incident,
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.models.incident_memory import (
    IncidentMemory,
)
from ops_pilot.schemas.action_execution import (
    RefundExecutionResult,
)
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
)
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryCreate,
)
from ops_pilot.tools.schemas import (
    ToolExecutionResult,
)


def normalize_category(
    category: IncidentCategory | str,
) -> str:
    if isinstance(
        category,
        IncidentCategory,
    ):
        return category.value

    return str(category)


def normalize_priority(
    priority: IncidentPriority | str,
) -> str:
    if isinstance(
        priority,
        IncidentPriority,
    ):
        return priority.value

    return str(priority)


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


async def create_or_get_incident_memory(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    payload: IncidentMemoryCreate,
) -> IncidentMemory:
    existing = await get_incident_memory(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

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
        subject_customer_id=(incident.subject_customer_id),
        category=incident.category,
        summary=payload.summary,
        resolution=payload.resolution,
    )

    session.add(
        memory,
    )

    try:
        await session.commit()

    except IntegrityError as exc:
        # Another worker/request may have created
        # the same incident memory concurrently.
        await session.rollback()

        existing = await get_incident_memory(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )

        if existing is not None:
            return existing

        raise exc

    except Exception:
        await session.rollback()
        raise

    await session.refresh(
        memory,
    )

    return memory


async def generate_and_store_incident_memory(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    title: str,
    description: str,
    category: IncidentCategory | str,
    priority: IncidentPriority | str,
    analysis: str,
    recommendation: str,
    tool_results: list[ToolExecutionResult],
    execution: RefundExecutionResult | None,
) -> IncidentMemory:
    existing = await get_incident_memory(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

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

    category_value = normalize_category(
        category,
    )

    if incident.category != category_value:
        raise IncidentMemoryInvalidIncidentError

    if incident.priority is None:
        raise IncidentMemoryInvalidIncidentError

    priority_value = normalize_priority(
        priority,
    )

    incident_priority_value = normalize_priority(
        incident.priority,
    )

    if incident_priority_value != priority_value:
        raise IncidentMemoryInvalidIncidentError

    await session.rollback()

    memory_payload = await generate_incident_memory(
        title=title,
        description=description,
        category=category_value,
        priority=priority_value,
        analysis=analysis,
        recommendation=recommendation,
        tool_results=tool_results,
        execution=execution,
    )

    return await create_or_get_incident_memory(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        payload=memory_payload,
    )
