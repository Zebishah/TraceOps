import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.integrations.n8n import send_n8n_event
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.schemas.automation_events import (
    AutomationEvent,
    DocumentIndexingFailedPayload,
    HighRiskIncidentPayload,
    IncidentResolvedPayload,
)


async def build_incident_resolved_event(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> AutomationEvent:
    result = await session.execute(
        select(Incident).where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
    )

    incident = result.scalar_one_or_none()

    if incident is None:
        raise RuntimeError("Incident not found")

    if incident.status != IncidentStatus.RESOLVED:
        raise RuntimeError("Incident must be resolved before automation dispatch")

    customer_email: str | None = None
    customer_name: str | None = None

    if incident.subject_customer_id is not None:
        customer_result = await session.execute(
            select(Customer).where(
                Customer.id == incident.subject_customer_id,
                Customer.organization_id == organization_id,
            )
        )

        customer = customer_result.scalar_one_or_none()

        if customer is not None:
            customer_email = customer.email
            customer_name = customer.full_name

    payload = IncidentResolvedPayload(
        incident_id=incident.id,
        title=incident.title,
        category=incident.category,
        priority=(incident.priority.value if incident.priority is not None else None),
        customer_id=incident.subject_customer_id,
        customer_email=customer_email,
        customer_name=customer_name,
    )

    return AutomationEvent(
        event_id=uuid.uuid4(),
        event_type="incident.resolved",
        organization_id=organization_id,
        occurred_at=datetime.now(UTC),
        payload=payload,
    )


async def dispatch_incident_resolved_automation(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> None:
    event = await build_incident_resolved_event(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    await send_n8n_event(
        webhook_path="incident-resolved",
        event=event,
    )


async def dispatch_high_risk_incident_automation(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    title: str,
    priority: str,
    category: str | None,
) -> None:
    event = AutomationEvent(
        event_id=uuid.uuid4(),
        event_type="incident.high_risk",
        organization_id=organization_id,
        occurred_at=datetime.now(UTC),
        payload=HighRiskIncidentPayload(
            incident_id=incident_id,
            title=title,
            priority=priority,
            category=category,
        ),
    )

    await send_n8n_event(
        webhook_path="incident-high-risk",
        event=event,
    )


async def dispatch_document_indexing_failed_automation(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    job_id: uuid.UUID,
    filename: str,
    error_message: str,
) -> None:
    event = AutomationEvent(
        event_id=uuid.uuid4(),
        event_type="document.indexing_failed",
        organization_id=organization_id,
        occurred_at=datetime.now(UTC),
        payload=DocumentIndexingFailedPayload(
            document_id=document_id,
            job_id=job_id,
            filename=filename,
            error_message=error_message,
        ),
    )

    await send_n8n_event(
        webhook_path="document-indexing-failed",
        event=event,
    )
