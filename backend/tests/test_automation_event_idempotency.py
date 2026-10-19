import uuid

from ops_pilot.services.automation_events import (
    build_automation_event_id,
)


def test_same_automation_event_produces_same_id() -> None:
    organization_id = uuid.uuid4()

    first = build_automation_event_id(
        organization_id=organization_id,
        event_type="incident.resolved",
        resource_key="incident-123",
    )

    second = build_automation_event_id(
        organization_id=organization_id,
        event_type="incident.resolved",
        resource_key="incident-123",
    )

    assert first == second


def test_different_resource_produces_different_event_id() -> None:
    organization_id = uuid.uuid4()

    first = build_automation_event_id(
        organization_id=organization_id,
        event_type="incident.resolved",
        resource_key="incident-123",
    )

    second = build_automation_event_id(
        organization_id=organization_id,
        event_type="incident.resolved",
        resource_key="incident-456",
    )

    assert first != second


def test_different_event_type_produces_different_event_id() -> None:
    organization_id = uuid.uuid4()

    first = build_automation_event_id(
        organization_id=organization_id,
        event_type="incident.resolved",
        resource_key="incident-123",
    )

    second = build_automation_event_id(
        organization_id=organization_id,
        event_type="incident.high_risk",
        resource_key="incident-123",
    )

    assert first != second


def test_different_organization_produces_different_event_id() -> None:
    first = build_automation_event_id(
        organization_id=uuid.uuid4(),
        event_type="incident.resolved",
        resource_key="incident-123",
    )

    second = build_automation_event_id(
        organization_id=uuid.uuid4(),
        event_type="incident.resolved",
        resource_key="incident-123",
    )

    assert first != second
