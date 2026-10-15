import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.models.incident import (
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.services.mcp_incidents import (
    get_incident_detail,
    list_open_incidents,
    search_incidents,
)

ORGANIZATION_ID = uuid.uuid4()
OTHER_ORGANIZATION_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()


def make_incident(
    *,
    incident_id: uuid.UUID = INCIDENT_ID,
    organization_id: uuid.UUID = ORGANIZATION_ID,
    title: str = "Customer charged twice",
    description: str = "Customer reports two charges for one order.",
    status: IncidentStatus = IncidentStatus.INVESTIGATING,
    category: str | None = "payment",
    priority: IncidentPriority | None = IncidentPriority.HIGH,
) -> SimpleNamespace:
    now = datetime.now(UTC)

    return SimpleNamespace(
        id=incident_id,
        organization_id=organization_id,
        created_by_user_id=uuid.uuid4(),
        subject_customer_id=uuid.uuid4(),
        title=title,
        description=description,
        status=status,
        category=category,
        priority=priority,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.anyio
async def test_list_open_incidents_returns_structured_results() -> None:
    session = AsyncMock()

    scalar_result = Mock()
    scalar_result.all.return_value = [
        make_incident(),
    ]

    result = Mock()
    result.scalars.return_value = scalar_result

    session.execute.return_value = result

    incidents = await list_open_incidents(
        session=session,
        organization_id=ORGANIZATION_ID,
        limit=10,
    )

    assert len(incidents) == 1

    assert incidents[0].id == INCIDENT_ID
    assert incidents[0].title == "Customer charged twice"
    assert incidents[0].status == IncidentStatus.INVESTIGATING
    assert incidents[0].category == "payment"
    assert incidents[0].priority == IncidentPriority.HIGH

    session.execute.assert_awaited_once()


@pytest.mark.anyio
async def test_search_incidents_returns_matching_results() -> None:
    session = AsyncMock()

    scalar_result = Mock()
    scalar_result.all.return_value = [
        make_incident(),
    ]

    result = Mock()
    result.scalars.return_value = scalar_result

    session.execute.return_value = result

    incidents = await search_incidents(
        session=session,
        organization_id=ORGANIZATION_ID,
        query="charged twice",
        limit=5,
    )

    assert len(incidents) == 1
    assert incidents[0].id == INCIDENT_ID
    assert incidents[0].category == "payment"

    session.execute.assert_awaited_once()


@pytest.mark.anyio
async def test_search_incidents_empty_query_returns_no_results() -> None:
    session = AsyncMock()

    incidents = await search_incidents(
        session=session,
        organization_id=ORGANIZATION_ID,
        query="   ",
    )

    assert incidents == []

    session.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_get_incident_detail_returns_incident() -> None:
    session = AsyncMock()

    result = Mock()
    result.scalar_one_or_none.return_value = make_incident()

    session.execute.return_value = result

    incident = await get_incident_detail(
        session=session,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
    )

    assert incident is not None
    assert incident.id == INCIDENT_ID
    assert incident.organization_id == ORGANIZATION_ID
    assert incident.description == ("Customer reports two charges for one order.")


@pytest.mark.anyio
async def test_get_incident_detail_returns_none_when_missing() -> None:
    session = AsyncMock()

    result = Mock()
    result.scalar_one_or_none.return_value = None

    session.execute.return_value = result

    incident = await get_incident_detail(
        session=session,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
    )

    assert incident is None


@pytest.mark.anyio
async def test_get_incident_detail_is_tenant_scoped() -> None:
    session = AsyncMock()

    result = Mock()
    result.scalar_one_or_none.return_value = None

    session.execute.return_value = result

    incident = await get_incident_detail(
        session=session,
        organization_id=OTHER_ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
    )

    assert incident is None

    session.execute.assert_awaited_once()
