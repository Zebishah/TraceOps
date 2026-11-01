import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.approval import (
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.services.automation_events import (
    build_incident_resolved_event,
)
from ops_pilot.services.automation_outbox import (
    enqueue_automation_in_session,
)


class IncidentResolutionConflict(Exception):
    pass


class IncidentResolutionNotFound(Exception):
    pass


async def resolve_incident_without_action(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    resolved_by_user_id: uuid.UUID,
    reason: str,
) -> Incident:
    reason = reason.strip()

    if len(reason) < 10:
        raise ValueError("Resolution reason must contain at least 10 characters")

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
            raise IncidentResolutionNotFound("Incident not found")

        if incident.status != IncidentStatus.INVESTIGATING:
            raise IncidentResolutionConflict(
                "Only investigating incidents can be resolved without action"
            )

        approval_result = await session.execute(
            select(ApprovalRequest.id)
            .where(
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.incident_id == incident_id,
                ApprovalRequest.status.in_(
                    [
                        ApprovalStatus.PENDING,
                        ApprovalStatus.APPROVED,
                        ApprovalStatus.EXECUTED,
                    ]
                ),
            )
            .limit(1)
        )

        if approval_result.scalar_one_or_none() is not None:
            raise IncidentResolutionConflict(
                "Cannot resolve without action while a pending, "
                "approved, or executed approval exists"
            )

        incident.status = IncidentStatus.RESOLVED
        incident.resolved_by_user_id = resolved_by_user_id
        incident.resolution_reason = reason
        incident.resolved_at = datetime.now(UTC)

        await session.flush()

        # Construct the event from the actual resolved incident.
        event = await build_incident_resolved_event(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )

        # Save the event in the same transaction as the resolution.
        # Inngest recovery can deliver it if n8n is unavailable.
        await enqueue_automation_in_session(
            session=session,
            webhook_path="incident-resolved",
            event=event,
        )

        await session.commit()

    except Exception:
        await session.rollback()
        raise

    await session.refresh(incident)
    return incident
