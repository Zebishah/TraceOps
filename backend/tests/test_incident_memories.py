import asyncio
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.incident_memories as memory_service_module
from ops_pilot.core.exceptions import (
    IncidentMemoryInvalidIncidentError,
    IncidentMemoryNotReadyError,
    IncidentNotFoundError,
)
from ops_pilot.models.incident import (
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.models.incident_memory import IncidentMemory
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
)
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryCreate,
)
from ops_pilot.services.incident_memories import (
    create_or_get_incident_memory,
    generate_and_store_incident_memory,
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


def test_generate_and_store_incident_memory_uses_ai_payload(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    session = AsyncMock(spec=AsyncSession)

    no_existing_result = Mock()
    no_existing_result.scalar_one_or_none.return_value = None

    incident = SimpleNamespace(
        id=incident_id,
        organization_id=organization_id,
        subject_customer_id=customer_id,
        category=IncidentCategory.PAYMENT.value,
        priority=IncidentPriority.HIGH,
        status=IncidentStatus.RESOLVED,
    )

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    session.execute.side_effect = [
        no_existing_result,
        incident_result,
    ]

    generated_payload = IncidentMemoryCreate(
        summary="Two charges were confirmed for one order.",
        resolution="The duplicate charge was refunded.",
    )

    async def fake_generate_incident_memory(
        **kwargs: object,
    ) -> IncidentMemoryCreate:
        return generated_payload

    expected_memory = IncidentMemory(
        organization_id=organization_id,
        incident_id=incident_id,
        subject_customer_id=customer_id,
        category="payment",
        summary=generated_payload.summary,
        resolution=generated_payload.resolution,
    )

    async def fake_create_or_get_incident_memory(
        **kwargs: object,
    ) -> IncidentMemory:
        assert kwargs["organization_id"] == organization_id
        assert kwargs["incident_id"] == incident_id
        assert kwargs["payload"] == generated_payload

        return expected_memory

    monkeypatch.setattr(
        memory_service_module,
        "generate_incident_memory",
        fake_generate_incident_memory,
    )

    monkeypatch.setattr(
        memory_service_module,
        "create_or_get_incident_memory",
        fake_create_or_get_incident_memory,
    )

    async def run() -> None:
        result = await generate_and_store_incident_memory(
            session=cast(AsyncSession, session),
            organization_id=organization_id,
            incident_id=incident_id,
            title="Customer charged twice",
            description="Customer was charged twice.",
            category=IncidentCategory.PAYMENT,
            priority=IncidentPriority.HIGH,
            analysis="Duplicate payment confirmed.",
            recommendation="Refund duplicate transaction.",
            tool_results=[],
            execution=None,
        )

        assert result is expected_memory

    asyncio.run(run())

    session.rollback.assert_awaited_once()


def test_generate_memory_skips_ai_when_memory_exists(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    existing_memory = IncidentMemory(
        id=uuid.uuid4(),
        organization_id=organization_id,
        incident_id=incident_id,
        subject_customer_id=None,
        category="payment",
        summary="Existing memory.",
        resolution="Already resolved.",
    )

    async def fake_get_incident_memory(
        **kwargs: object,
    ) -> IncidentMemory:
        return existing_memory

    generate_mock = AsyncMock()

    monkeypatch.setattr(
        memory_service_module,
        "get_incident_memory",
        fake_get_incident_memory,
    )

    monkeypatch.setattr(
        memory_service_module,
        "generate_incident_memory",
        generate_mock,
    )

    result = asyncio.run(
        generate_and_store_incident_memory(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            title="Duplicate payment",
            description="Customer charged twice.",
            category=(IncidentCategory.PAYMENT),
            priority=(IncidentPriority.HIGH),
            analysis="Confirmed duplicate.",
            recommendation=("Refund duplicate."),
            tool_results=[],
            execution=None,
        )
    )

    assert result is existing_memory

    generate_mock.assert_not_awaited()
