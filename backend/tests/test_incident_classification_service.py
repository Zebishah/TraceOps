import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import ops_pilot.services.incident_classification as service_module
from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
    IncidentClassification,
)


def test_classify_stored_incident_updates_incident(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    incident = SimpleNamespace(
        id=incident_id,
        title="Customer charged twice",
        description="Customer was charged twice for one order.",
        category=None,
        priority=None,
        status=IncidentStatus.NEW,
    )

    classification = IncidentClassification(
        category=IncidentCategory.PAYMENT,
        priority=IncidentPriority.HIGH,
        confidence=0.98,
    )

    async def fake_get_incident(
        *,
        session,
        organization_id,
        incident_id,
    ):
        return incident

    async def fake_classify_incident(
        *,
        title,
        description,
    ):
        assert title == incident.title
        assert description == incident.description

        return classification

    monkeypatch.setattr(
        service_module,
        "get_incident",
        fake_get_incident,
    )

    monkeypatch.setattr(
        service_module,
        "classify_incident",
        fake_classify_incident,
    )

    session = AsyncMock()

    # Simulate PostgreSQL returning the locked incident.
    db_result = Mock()
    db_result.scalar_one_or_none.return_value = incident

    session.execute.return_value = db_result

    saved_incident, result = asyncio.run(
        service_module.classify_stored_incident(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )
    )

    assert saved_incident.category == "payment"
    assert saved_incident.priority == IncidentPriority.HIGH
    assert saved_incident.status == IncidentStatus.INVESTIGATING

    assert result == classification

    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(incident)
    session.rollback.assert_awaited_once()


def test_classification_failure_does_not_commit(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    incident = SimpleNamespace(
        id=incident_id,
        title="Customer charged twice",
        description="Customer was charged twice for one order.",
        category=None,
        priority=None,
        status=IncidentStatus.NEW,
    )

    async def fake_get_incident(
        *,
        session,
        organization_id,
        incident_id,
    ):
        return incident

    async def fake_classify_incident(
        *,
        title,
        description,
    ):
        raise RuntimeError("AI provider failed")

    monkeypatch.setattr(
        service_module,
        "get_incident",
        fake_get_incident,
    )

    monkeypatch.setattr(
        service_module,
        "classify_incident",
        fake_classify_incident,
    )

    session = AsyncMock()

    with pytest.raises(
        RuntimeError,
        match="AI provider failed",
    ):
        asyncio.run(
            service_module.classify_stored_incident(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
            )
        )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.refresh.assert_not_awaited()


def test_classification_cannot_reopen_resolved_incident(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    incident = SimpleNamespace(
        id=incident_id,
        title="Customer charged twice",
        description="Two payments were reported.",
        category=None,
        priority=None,
        status=IncidentStatus.NEW,
    )

    async def fake_get_incident(**kwargs):
        return incident

    async def fake_classify_incident(**kwargs):
        # Simulate another request resolving the incident
        # while the AI classification was running.
        incident.status = IncidentStatus.RESOLVED

        return IncidentClassification(
            category=IncidentCategory.PAYMENT,
            priority=IncidentPriority.HIGH,
            confidence=0.98,
        )

    monkeypatch.setattr(
        service_module,
        "get_incident",
        fake_get_incident,
    )

    monkeypatch.setattr(
        service_module,
        "classify_incident",
        fake_classify_incident,
    )

    session = AsyncMock()

    db_result = Mock()
    db_result.scalar_one_or_none.return_value = incident
    session.execute.return_value = db_result

    from ops_pilot.services.incident_resolution import (
        IncidentResolutionConflict,
    )

    with pytest.raises(
        IncidentResolutionConflict,
        match="Incident state changed during classification",
    ):
        asyncio.run(
            service_module.classify_stored_incident(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
            )
        )

    session.commit.assert_not_awaited()
    assert incident.status == IncidentStatus.RESOLVED
