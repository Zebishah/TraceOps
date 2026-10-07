import asyncio
import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.incidents as incidents_module
from ops_pilot.models.incident import (
    Incident,
    IncidentStatus,
)
from ops_pilot.schemas.incidents import (
    IncidentResponse,
)


def build_incident_response(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> IncidentResponse:
    now = datetime.now(
        UTC,
    )

    return IncidentResponse(
        id=incident_id,
        organization_id=organization_id,
        created_by_user_id=uuid.uuid4(),
        subject_customer_id=None,
        title="Duplicate payment",
        description="Customer charged twice.",
        status=IncidentStatus.NEW,
        category=None,
        priority=None,
        created_at=now,
        updated_at=now,
    )


def test_get_incident_response_uses_cache(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    expected = build_incident_response(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    async def fake_get_incident_cache(
        **kwargs: object,
    ) -> dict[str, object]:
        return expected.model_dump(
            mode="json",
        )

    get_incident_mock = AsyncMock()

    monkeypatch.setattr(
        incidents_module,
        "get_incident_cache",
        fake_get_incident_cache,
    )

    monkeypatch.setattr(
        incidents_module,
        "get_incident",
        get_incident_mock,
    )

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    result = asyncio.run(
        incidents_module.get_incident_response_cached(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )
    )

    assert result == expected

    get_incident_mock.assert_not_awaited()


def test_get_incident_response_caches_database_result(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    user_id = uuid.uuid4()

    now = datetime.now(
        UTC,
    )

    incident = Incident(
        id=incident_id,
        organization_id=organization_id,
        created_by_user_id=user_id,
        subject_customer_id=None,
        title="Duplicate payment",
        description="Customer charged twice.",
        status=IncidentStatus.NEW,
        created_at=now,
        updated_at=now,
    )

    async def fake_get_incident_cache(
        **kwargs: object,
    ) -> None:
        return None

    async def fake_get_incident(
        **kwargs: object,
    ) -> Incident:
        return incident

    set_cache_mock = AsyncMock()

    monkeypatch.setattr(
        incidents_module,
        "get_incident_cache",
        fake_get_incident_cache,
    )

    monkeypatch.setattr(
        incidents_module,
        "get_incident",
        fake_get_incident,
    )

    monkeypatch.setattr(
        incidents_module,
        "set_incident_cache",
        set_cache_mock,
    )

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    result = asyncio.run(
        incidents_module.get_incident_response_cached(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )
    )

    assert result.id == incident_id

    set_cache_mock.assert_awaited_once()


def test_redis_failure_falls_back_to_database(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    user_id = uuid.uuid4()

    now = datetime.now(
        UTC,
    )

    incident = Incident(
        id=incident_id,
        organization_id=organization_id,
        created_by_user_id=user_id,
        subject_customer_id=None,
        title="Duplicate payment",
        description="Customer charged twice.",
        status=IncidentStatus.NEW,
        created_at=now,
        updated_at=now,
    )

    async def fake_get_incident_cache(
        **kwargs: object,
    ) -> dict[str, object] | None:
        raise RuntimeError("Redis unavailable")

    async def fake_get_incident(
        **kwargs: object,
    ) -> Incident:
        return incident

    monkeypatch.setattr(
        incidents_module,
        "get_incident_cache",
        fake_get_incident_cache,
    )

    monkeypatch.setattr(
        incidents_module,
        "get_incident",
        fake_get_incident,
    )

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    result = asyncio.run(
        incidents_module.get_incident_response_cached(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )
    )

    assert result.id == incident_id
