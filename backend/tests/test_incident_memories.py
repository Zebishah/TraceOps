import asyncio
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    IncidentMemoryInvalidIncidentError,
    IncidentMemoryNotReadyError,
    IncidentNotFoundError,
)
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.models.incident_memory import IncidentMemory
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryCreate,
)
from ops_pilot.services.incident_memories import (
    create_or_get_incident_memory,
)


def test_create_incident_memory_requires_existing_incident() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    session = AsyncMock(spec=AsyncSession)

    existing_result = Mock()
    existing_result.scalar_one_or_none.return_value = None

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = None

    session.execute.side_effect = [
        existing_result,
        incident_result,
    ]

    payload = IncidentMemoryCreate(
        summary="Customer was charged twice.",
        resolution="Duplicate charge was refunded.",
    )

    async def run() -> None:
        with pytest.raises(IncidentNotFoundError):
            await create_or_get_incident_memory(
                session=cast(AsyncSession, session),
                organization_id=organization_id,
                incident_id=incident_id,
                payload=payload,
            )

    asyncio.run(run())

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_create_incident_memory_requires_resolved_incident() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    session = AsyncMock(spec=AsyncSession)

    existing_result = Mock()
    existing_result.scalar_one_or_none.return_value = None

    incident = SimpleNamespace(
        id=incident_id,
        organization_id=organization_id,
        subject_customer_id=uuid.uuid4(),
        category="payment",
        status=IncidentStatus.INVESTIGATING,
    )

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    session.execute.side_effect = [
        existing_result,
        incident_result,
    ]

    payload = IncidentMemoryCreate(
        summary="Customer was charged twice.",
        resolution="Duplicate charge was refunded.",
    )

    async def run() -> None:
        with pytest.raises(IncidentMemoryNotReadyError):
            await create_or_get_incident_memory(
                session=cast(AsyncSession, session),
                organization_id=organization_id,
                incident_id=incident_id,
                payload=payload,
            )

    asyncio.run(run())

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_create_incident_memory_requires_category() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    session = AsyncMock(spec=AsyncSession)

    existing_result = Mock()
    existing_result.scalar_one_or_none.return_value = None

    incident = SimpleNamespace(
        id=incident_id,
        organization_id=organization_id,
        subject_customer_id=None,
        category=None,
        status=IncidentStatus.RESOLVED,
    )

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    session.execute.side_effect = [
        existing_result,
        incident_result,
    ]

    payload = IncidentMemoryCreate(
        summary="Customer was charged twice.",
        resolution="Duplicate charge was refunded.",
    )

    async def run() -> None:
        with pytest.raises(IncidentMemoryInvalidIncidentError):
            await create_or_get_incident_memory(
                session=cast(AsyncSession, session),
                organization_id=organization_id,
                incident_id=incident_id,
                payload=payload,
            )

    asyncio.run(run())

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_create_incident_memory_returns_existing_memory() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    session = AsyncMock(spec=AsyncSession)

    existing_memory = IncidentMemory(
        organization_id=organization_id,
        incident_id=incident_id,
        subject_customer_id=None,
        category="payment",
        summary="Existing summary",
        resolution="Existing resolution",
    )

    existing_result = Mock()
    existing_result.scalar_one_or_none.return_value = existing_memory

    session.execute.return_value = existing_result

    payload = IncidentMemoryCreate(
        summary="New summary",
        resolution="New resolution",
    )

    async def run() -> None:
        result = await create_or_get_incident_memory(
            session=cast(AsyncSession, session),
            organization_id=organization_id,
            incident_id=incident_id,
            payload=payload,
        )

        assert result is existing_memory

    asyncio.run(run())

    session.add.assert_not_called()
    session.commit.assert_not_awaited()
