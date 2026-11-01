"""Authenticated, durable high-risk incident acknowledgment."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.automation_delivery import AutomationDelivery
from ops_pilot.models.incident import (
    Incident,
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.schemas.automation_events import (
    AutomationEvent,
    IncidentAcknowledgedPayload,
)
from ops_pilot.services.automation_events import (
    build_automation_event_id,
)
from ops_pilot.services.automation_outbox import (
    enqueue_automation_in_session,
)


class IncidentAcknowledgmentNotFound(Exception):
    pass


class IncidentAcknowledgmentConflict(Exception):
    pass


async def acknowledge_incident(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    responder_id: uuid.UUID,
) -> uuid.UUID:
    """Queue one acknowledgment for an eligible high-risk incident.

    Acknowledgment does not alter the canonical AI investigation
    status. n8n owns the separate notification/SLA acknowledgment.
    """
    try:
        result = await session.execute(
            select(Incident)
            .where(
                Incident.id == incident_id,
                Incident.organization_id == organization_id,
            )
            .with_for_update()
        )

        incident = result.scalar_one_or_none()

        if incident is None:
            raise IncidentAcknowledgmentNotFound("Incident not found")

        if incident.priority not in (
            IncidentPriority.HIGH,
            IncidentPriority.CRITICAL,
        ):
            raise IncidentAcknowledgmentConflict("Only high-risk incidents can be acknowledged")

        if incident.status in (
            IncidentStatus.RESOLVED,
            IncidentStatus.FAILED,
        ):
            raise IncidentAcknowledgmentConflict("Closed incidents cannot be acknowledged")

        event_id = build_automation_event_id(
            organization_id=organization_id,
            event_type="incident.acknowledged",
            resource_key=str(incident_id),
        )

        existing = await session.get(
            AutomationDelivery,
            event_id,
        )

        if existing is not None:
            if (
                existing.organization_id != organization_id
                or existing.event_type != "incident.acknowledged"
                or existing.webhook_path != "incident-acknowledged"
            ):
                raise IncidentAcknowledgmentConflict("Existing acknowledgment event conflicts")

            # Idempotency: the first accepted responder wins.
            await session.rollback()
            return event_id

        high_risk_event_id = build_automation_event_id(
            organization_id=organization_id,
            event_type="incident.high_risk",
            resource_key=str(incident_id),
        )

        high_risk_event = await session.get(
            AutomationDelivery,
            high_risk_event_id,
        )

        if (
            high_risk_event is None
            or high_risk_event.organization_id != organization_id
            or high_risk_event.event_type != "incident.high_risk"
        ):
            raise IncidentAcknowledgmentConflict(
                "High-risk incident automation has not been queued"
            )

        event = AutomationEvent(
            event_id=event_id,
            event_type="incident.acknowledged",
            organization_id=organization_id,
            occurred_at=datetime.now(UTC),
            payload=IncidentAcknowledgedPayload(
                incident_id=incident_id,
                responder_id=responder_id,
            ),
        )

        await enqueue_automation_in_session(
            session=session,
            webhook_path="incident-acknowledged",
            event=event,
        )

        await session.commit()

        return event_id

    except Exception:
        await session.rollback()
        raise
