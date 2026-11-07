import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.automation_delivery import AutomationDelivery
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.schemas.action_execution import (
    RefundExecutionResult,
)
from ops_pilot.schemas.automation_events import (
    AutomationEvent,
    CustomerRecoveryPayload,
    DocumentIndexingFailedPayload,
    HighRiskIncidentPayload,
    IncidentResolvedPayload,
)
from ops_pilot.services.automation_outbox import (
    deliver_automation,
    queue_and_attempt_automation,
)


def build_automation_event_id(
    *,
    organization_id: uuid.UUID,
    event_type: str,
    resource_key: str,
) -> uuid.UUID:
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        (f"ops-pilot:{organization_id}:{event_type}:{resource_key}"),
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
        event_id=build_automation_event_id(
            organization_id=organization_id,
            event_type="incident.resolved",
            resource_key=str(incident.id),
        ),
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

    await queue_and_attempt_automation(
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
        event_id=build_automation_event_id(
            organization_id=organization_id,
            event_type="incident.high_risk",
            resource_key=str(incident_id),
        ),
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

    await queue_and_attempt_automation(
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
        event_id=build_automation_event_id(
            organization_id=organization_id,
            event_type="document.indexing_failed",
            resource_key=str(job_id),
        ),
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

    await queue_and_attempt_automation(
        webhook_path="document-indexing-failed",
        event=event,
    )


async def build_customer_recovery_event(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    title: str,
    category: str,
    priority: str,
    customer_id: uuid.UUID,
    execution: RefundExecutionResult,
) -> AutomationEvent:
    customer_result = await session.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
        )
    )

    customer = customer_result.scalar_one_or_none()

    if customer is None:
        raise RuntimeError("Customer not found for recovery automation")

    resolution = (
        f"Simulated refund of {execution.amount} "
        f"{execution.currency} recorded successfully "
        f"in TraceOps's internal ledger for transaction "
        f"{execution.source_transaction_id}. "
        "No external payment provider was contacted."
    )

    return AutomationEvent(
        event_id=build_automation_event_id(
            organization_id=organization_id,
            event_type="incident.customer_recovery",
            resource_key=execution.refund_transaction_id,
        ),
        event_type="incident.customer_recovery",
        organization_id=organization_id,
        occurred_at=datetime.now(UTC),
        payload=CustomerRecoveryPayload(
            incident_id=incident_id,
            title=title,
            category=category,
            priority=priority,
            customer_id=customer.id,
            customer_name=customer.full_name,
            customer_email=customer.email,
            resolution=resolution,
            action_type="refund_transaction",
            source_transaction_id=execution.source_transaction_id,
            refund_transaction_id=execution.refund_transaction_id,
            refund_amount=execution.amount,
            currency=execution.currency,
        ),
    )


async def dispatch_customer_recovery_automation(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    title: str,
    category: str,
    priority: str,
    customer_id: uuid.UUID,
    execution: RefundExecutionResult,
) -> None:

    event_id = build_automation_event_id(
        organization_id=organization_id,
        event_type="incident.customer_recovery",
        resource_key=execution.refund_transaction_id,
    )

    # A newly committed refund must already have an outbox
    # record created in the same database transaction.
    existing = await session.get(
        AutomationDelivery,
        event_id,
    )

    if existing is None:
        # Fail closed instead of silently creating a new
        # post-commit notification outside the refund transaction.
        raise RuntimeError("Customer recovery outbox event missing after refund transaction")

    if (
        existing.organization_id != organization_id
        or existing.event_type != "incident.customer_recovery"
        or existing.webhook_path != "incident-customer-recovery"
    ):
        raise RuntimeError("Customer recovery outbox event identity mismatch")

    # The delivery service loads the original persisted payload.
    # It does not rebuild the notification from workflow state.
    # If n8n is unavailable, scheduled outbox recovery handles it.
    await deliver_automation(delivery_id=event_id)
