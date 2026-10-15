import uuid
from unittest.mock import AsyncMock

import pytest

from ops_pilot.services import mcp_investigation

ORGANIZATION_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()


@pytest.mark.anyio
async def test_investigate_incident_for_mcp_rejects_missing_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    fake_get_incident = AsyncMock(
        return_value=None,
    )

    fake_investigate = AsyncMock()

    monkeypatch.setattr(
        mcp_investigation,
        "get_incident_detail",
        fake_get_incident,
    )

    monkeypatch.setattr(
        mcp_investigation,
        "investigate_incident",
        fake_investigate,
    )

    result = await mcp_investigation.investigate_incident_for_mcp(
        session=session,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
    )

    assert result is None

    fake_get_incident.assert_awaited_once_with(
        session=session,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
    )

    fake_investigate.assert_not_awaited()


@pytest.mark.anyio
async def test_investigate_incident_for_mcp_reuses_existing_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    fake_get_incident = AsyncMock(
        return_value=object(),
    )

    fake_response = AsyncMock()

    fake_investigate = AsyncMock(
        return_value=fake_response,
    )

    monkeypatch.setattr(
        mcp_investigation,
        "get_incident_detail",
        fake_get_incident,
    )

    monkeypatch.setattr(
        mcp_investigation,
        "investigate_incident",
        fake_investigate,
    )

    result = await mcp_investigation.investigate_incident_for_mcp(
        session=session,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
    )

    assert result is fake_response

    fake_investigate.assert_awaited_once_with(
        session=session,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
    )
