"""Real PostgreSQL integration tests for the automation outbox."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

import ops_pilot.services.automation_outbox as outbox
from ops_pilot.models.automation_delivery import AutomationDelivery
from ops_pilot.models.organization import Organization
from ops_pilot.schemas.automation_events import (
    AutomationEvent,
    HighRiskIncidentPayload,
)

EXPECTED_HOST = "ep-bold-sea-b5exs2wm-pooler.c-7.us-east-2.aws.neon.tech"


@pytest.mark.asyncio
async def test_automation_outbox_postgres_concurrency() -> None:
    database_url = os.environ.get("OPSPILOT_TEST_DATABASE_URL")

    if not database_url:
        pytest.skip("Dedicated PostgreSQL test URL required")

    parsed = make_url(database_url)

    if parsed.get_backend_name() != "postgresql" or parsed.host != EXPECTED_HOST:
        pytest.fail("Refusing to use a non-dedicated TEST database")

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )

    sessions = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    organization_id = uuid.uuid4()
    event_id = uuid.uuid4()

    event = AutomationEvent(
        event_id=event_id,
        event_type="incident.high_risk",
        organization_id=organization_id,
        occurred_at=datetime.now(UTC),
        payload=HighRiskIncidentPayload(
            incident_id=uuid.uuid4(),
            title="Integration test incident",
            priority="critical",
            category="payment",
        ),
    )

    try:
        # Create only test-owned records.
        async with sessions() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name="Outbox concurrency test",
                    slug=f"outbox-test-{organization_id.hex}",
                )
            )
            await session.commit()

        with patch.object(
            outbox,
            "async_session_factory",
            sessions,
        ):
            # STEP 1: Enqueue the same event twice.
            await outbox.enqueue_automation(
                webhook_path="incident-high-risk",
                event=event,
            )
            await outbox.enqueue_automation(
                webhook_path="incident-high-risk",
                event=event,
            )

            # A duplicate event ID with different business
            # content must be rejected, not silently ignored.
            conflicting_event = event.model_copy(
                update={
                    "payload": HighRiskIncidentPayload(
                        incident_id=event.payload.incident_id,
                        title="Conflicting notification",
                        priority="critical",
                        category="payment",
                    ),
                }
            )

            with pytest.raises(
                RuntimeError,
                match="Conflicting automation event ID",
            ):
                await outbox.enqueue_automation(
                    webhook_path="incident-high-risk",
                    event=conflicting_event,
                )

            # Rejected conflict must not alter the stored row.
            async with sessions() as session:
                original = await session.get(
                    AutomationDelivery,
                    event_id,
                )

                assert original is not None
                assert original.payload["payload"]["title"] == ("Integration test incident")
                assert original.status == "pending"
                assert original.attempt_count == 0

            async with sessions() as session:
                result = await session.execute(
                    select(AutomationDelivery).where(AutomationDelivery.id == event_id)
                )
                records = result.scalars().all()

            assert len(records) == 1

            # STEP 2: Two workers compete for one delivery.
            first, second = await asyncio.gather(
                outbox.claim_delivery(delivery_id=event_id),
                outbox.claim_delivery(delivery_id=event_id),
            )

            winners = [claim for claim in (first, second) if claim is not None]

            assert len(winners) == 1

            old_token = winners[0][0]

            # STEP 3: Active lease prevents another claim.
            assert await outbox.claim_delivery(delivery_id=event_id) is None

            # STEP 4: Simulate an expired lease.
            async with sessions() as session:
                await session.execute(
                    update(AutomationDelivery)
                    .where(AutomationDelivery.id == event_id)
                    .values(lease_expires_at=(datetime.now(UTC) - timedelta(seconds=1)))
                )
                await session.commit()

            # STEP 5: Another worker can reclaim the event.
            new_claim = await outbox.claim_delivery(
                delivery_id=event_id,
            )

            assert new_claim is not None

            new_token = new_claim[0]

            assert new_token != old_token

            # STEP 6: Stale worker cannot finalize.
            stale_result = await outbox.finalize_delivery(
                delivery_id=event_id,
                token=old_token,
                error=None,
            )

            assert stale_result is False

            # STEP 7: Current worker can finalize.
            current_result = await outbox.finalize_delivery(
                delivery_id=event_id,
                token=new_token,
                error=None,
            )

            assert current_result is True

            # STEP 8: Verify final delivery state.
            async with sessions() as session:
                delivery = await session.get(
                    AutomationDelivery,
                    event_id,
                )

                assert delivery is not None
                assert delivery.status == "delivered"
                assert delivery.attempt_count == 2
                assert delivery.lease_token is None
                assert delivery.lease_expires_at is None
                assert delivery.delivered_at is not None

            # STEP 9: Delivered events cannot be claimed again.
            assert await outbox.claim_delivery(delivery_id=event_id) is None

    finally:
        try:
            async with sessions() as session:
                await session.execute(
                    delete(AutomationDelivery).where(
                        AutomationDelivery.id == event_id,
                        AutomationDelivery.organization_id == organization_id,
                    )
                )
                await session.execute(
                    delete(Organization).where(Organization.id == organization_id)
                )
                await session.commit()
        finally:
            await engine.dispose()
