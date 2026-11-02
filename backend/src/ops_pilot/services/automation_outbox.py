"""Durable, at-least-once delivery of n8n automation events."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.config import get_settings
from ops_pilot.db.session import async_session_factory
from ops_pilot.integrations.n8n import send_n8n_event
from ops_pilot.models.automation_delivery import AutomationDelivery
from ops_pilot.schemas.automation_events import AutomationEvent

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 8
DELIVERY_LEASE_SECONDS = 120
DELIVERY_BATCH_SIZE = 25
MAX_RETRY_DELAY_SECONDS = 3600


def retry_delay_seconds(attempt_count: int) -> int:
    """Exponential retry with a bounded delay."""
    if attempt_count <= 1:
        return 30

    # Avoid huge integer exponentiation for invalid input.
    exponent = min(attempt_count - 1, 7)

    delay: int = 30 * (2**exponent)

    return min(delay, MAX_RETRY_DELAY_SECONDS)


async def enqueue_automation_in_session(
    *,
    session: AsyncSession,
    webhook_path: str,
    event: AutomationEvent,
) -> None:
    """Insert an outbox event using the caller's transaction.

    This function never commits or rolls back. The caller owns
    the transaction and must commit its business changes and
    outbox insertion together.
    """
    event_data = event.model_dump(mode="json")

    values = {
        "id": event.event_id,
        "organization_id": event.organization_id,
        "event_type": event.event_type,
        "webhook_path": webhook_path,
        "payload": event_data,
        "status": "pending",
        "attempt_count": 0,
    }

    statement = (
        insert(AutomationDelivery)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(AutomationDelivery.id)
    )

    inserted_id = (await session.execute(statement)).scalar_one_or_none()

    if inserted_id is not None:
        return

    existing = (
        await session.execute(
            select(AutomationDelivery).where(
                AutomationDelivery.id == event.event_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        raise RuntimeError("Automation delivery disappeared after ID conflict")

    existing_payload = dict(existing.payload)
    incoming_payload = dict(event_data)

    existing_payload.pop("occurred_at", None)
    incoming_payload.pop("occurred_at", None)

    if (
        existing.organization_id != event.organization_id
        or existing.event_type != event.event_type
        or existing.webhook_path != webhook_path
        or existing_payload != incoming_payload
    ):
        raise RuntimeError(
            "Conflicting automation event ID: stored delivery differs from incoming event"
        )


async def enqueue_automation(
    *,
    webhook_path: str,
    event: AutomationEvent,
) -> None:
    """Enqueue independently when no business transaction exists."""

    async with async_session_factory() as session:
        async with session.begin():
            await enqueue_automation_in_session(
                session=session,
                webhook_path=webhook_path,
                event=event,
            )


async def claim_delivery(
    *,
    delivery_id: uuid.UUID,
) -> tuple[uuid.UUID, dict[str, Any], str] | None:
    """Claim one due event with an atomic, token-fenced update."""

    now = datetime.now(UTC)
    token = uuid.uuid4()
    lease_until = now + timedelta(
        seconds=DELIVERY_LEASE_SECONDS,
    )

    statement = (
        update(AutomationDelivery)
        .where(
            AutomationDelivery.id == delivery_id,
            AutomationDelivery.attempt_count < MAX_DELIVERY_ATTEMPTS,
            or_(
                (
                    (AutomationDelivery.status.in_(("pending", "retry")))
                    & (AutomationDelivery.next_attempt_at <= now)
                ),
                (
                    (AutomationDelivery.status == "processing")
                    & (AutomationDelivery.lease_expires_at <= now)
                ),
            ),
        )
        .values(
            status="processing",
            lease_token=token,
            lease_expires_at=lease_until,
            attempt_count=AutomationDelivery.attempt_count + 1,
        )
        .returning(
            AutomationDelivery.payload,
            AutomationDelivery.webhook_path,
        )
    )

    async with async_session_factory() as session:
        async with session.begin():
            row = (await session.execute(statement)).one_or_none()

    if row is None:
        return None

    return token, row.payload, row.webhook_path


async def finalize_delivery(
    *,
    delivery_id: uuid.UUID,
    token: uuid.UUID,
    error: Exception | None,
) -> bool:
    """Only the current lease owner may finalize the delivery."""

    now = datetime.now(UTC)

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(AutomationDelivery)
                .where(
                    AutomationDelivery.id == delivery_id,
                    AutomationDelivery.status == "processing",
                    AutomationDelivery.lease_token == token,
                )
                .with_for_update()
            )

            delivery = result.scalar_one_or_none()

            if delivery is None:
                return False

            delivery.lease_token = None
            delivery.lease_expires_at = None

            if error is None:
                delivery.status = "delivered"
                delivery.delivered_at = now
                delivery.last_error = None

            else:
                delivery.last_error = f"{type(error).__name__}: {error}"[:1000]

                if delivery.attempt_count >= MAX_DELIVERY_ATTEMPTS:
                    delivery.status = "dead"
                else:
                    delivery.status = "retry"
                    delivery.next_attempt_at = now + timedelta(
                        seconds=retry_delay_seconds(delivery.attempt_count)
                    )

    return True


async def deliver_automation(
    *,
    delivery_id: uuid.UUID,
) -> bool:
    """Attempt delivery without letting webhook outages escape to callers."""
    settings = get_settings()

    if not settings.n8n_delivery_enabled:
        logger.info(
            "automation_delivery_paused",
            extra={"delivery_id": str(delivery_id)},
        )
        return False

    claim = await claim_delivery(delivery_id=delivery_id)

    if claim is None:
        return False

    token, raw_event, webhook_path = claim
    error: Exception | None = None

    try:
        event = AutomationEvent.model_validate(raw_event)

        if event.event_id != delivery_id:
            raise ValueError(
                "Automation event ID does not match outbox ID",
            )

        # A total deadline also bounds slow responses that would otherwise
        # keep resetting individual HTTP read timeouts.
        async with asyncio.timeout(settings.n8n_timeout_seconds):
            await send_n8n_event(
                webhook_path=webhook_path,
                event=event,
            )

    except Exception as exc:
        error = exc

        logger.warning(
            "automation_delivery_failed",
            extra={"delivery_id": str(delivery_id)},
            exc_info=True,
        )

    finalized = await finalize_delivery(
        delivery_id=delivery_id,
        token=token,
        error=error,
    )

    if not finalized:
        logger.warning(
            "automation_delivery_lease_lost",
            extra={"delivery_id": str(delivery_id)},
        )
        return False

    return error is None


async def queue_and_attempt_automation(
    *,
    webhook_path: str,
    event: AutomationEvent,
) -> bool:
    """Durably save an event, then try immediate delivery."""

    await enqueue_automation(
        webhook_path=webhook_path,
        event=event,
    )

    return await deliver_automation(
        delivery_id=event.event_id,
    )


async def expire_exhausted_delivery_leases() -> int:
    """Close final-attempt deliveries abandoned by crashed workers.

    Never resend a delivery whose maximum attempt count was
    reached. Retain the row so the failure can be investigated.
    """

    now = datetime.now(UTC)

    statement = (
        update(AutomationDelivery)
        .where(
            AutomationDelivery.status == "processing",
            AutomationDelivery.attempt_count >= MAX_DELIVERY_ATTEMPTS,
            AutomationDelivery.lease_expires_at.is_not(None),
            AutomationDelivery.lease_expires_at <= now,
        )
        .values(
            status="dead",
            lease_token=None,
            lease_expires_at=None,
            last_error=("Delivery worker lease expired after the maximum permitted attempts"),
        )
        .returning(AutomationDelivery.id)
    )

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(statement)
            expired_ids = list(result.scalars().all())

    if expired_ids:
        logger.error(
            "automation_delivery_exhausted_leases",
            extra={"expired_count": len(expired_ids)},
        )

    return len(expired_ids)


async def recover_automation_deliveries() -> dict[str, int]:
    """Retry due deliveries and close exhausted leases."""

    # First, permanently close abandoned deliveries that
    # have already reached their maximum attempt count.
    if not get_settings().n8n_delivery_enabled:
        logger.info("automation_recovery_paused")

        return {
            "examined": 0,
            "delivered": 0,
            "expired": 0,
        }
    expired = await expire_exhausted_delivery_leases()

    now = datetime.now(UTC)

    async with async_session_factory() as session:
        result = await session.execute(
            select(AutomationDelivery.id)
            .where(
                AutomationDelivery.attempt_count < MAX_DELIVERY_ATTEMPTS,
                or_(
                    (AutomationDelivery.status.in_(("pending", "retry")))
                    & (AutomationDelivery.next_attempt_at <= now),
                    (AutomationDelivery.status == "processing")
                    & (AutomationDelivery.lease_expires_at <= now),
                ),
            )
            .order_by(
                AutomationDelivery.next_attempt_at,
                AutomationDelivery.id,
            )
            .limit(DELIVERY_BATCH_SIZE)
        )

        delivery_ids = list(result.scalars().all())

    succeeded = 0

    for delivery_id in delivery_ids:
        delivered = await deliver_automation(
            delivery_id=delivery_id,
        )

        if delivered:
            succeeded += 1

    return {
        "examined": len(delivery_ids),
        "delivered": succeeded,
        "expired": expired,
    }
