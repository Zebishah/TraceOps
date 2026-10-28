import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ops_pilot.models.automation_delivery import AutomationDelivery
from ops_pilot.models.organization import Organization
from ops_pilot.schemas.automation_events import (
    AutomationEvent,
    HighRiskIncidentPayload,
)
from ops_pilot.services.automation_outbox import (
    enqueue_automation_in_session,
)

EXPECTED_HOST = "ep-bold-sea-b5exs2wm-pooler.c-7.us-east-2.aws.neon.tech"


@pytest.mark.asyncio
async def test_outbox_insert_rolls_back_with_business_transaction() -> None:
    url = os.environ.get("OPSPILOT_TEST_DATABASE_URL")

    if not url:
        pytest.skip("Dedicated TEST database required")

    parsed = make_url(url)

    if parsed.host != EXPECTED_HOST or parsed.get_backend_name() != "postgresql":
        pytest.fail("Refusing non-test database")

    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    org_id = uuid.uuid4()
    event_id = uuid.uuid4()

    event = AutomationEvent(
        event_id=event_id,
        event_type="incident.high_risk",
        organization_id=org_id,
        occurred_at=datetime.now(UTC),
        payload=HighRiskIncidentPayload(
            incident_id=uuid.uuid4(),
            title="Atomic rollback test",
            priority="critical",
            category="payment",
        ),
    )

    try:
        # Both inserts belong to the same transaction.
        # Raising an exception forces its rollback.
        with pytest.raises(RuntimeError, match="simulated failure"):
            async with sessions() as session:
                async with session.begin():
                    session.add(
                        Organization(
                            id=org_id,
                            name="Atomic rollback test",
                            slug=f"atomic-{org_id.hex}",
                        )
                    )

                    await session.flush()

                    await enqueue_automation_in_session(
                        session=session,
                        webhook_path="incident-high-risk",
                        event=event,
                    )

                    raise RuntimeError("simulated failure")

        # Neither row should exist after rollback.
        async with sessions() as session:
            organization = await session.get(Organization, org_id)
            delivery = await session.get(AutomationDelivery, event_id)

            assert organization is None
            assert delivery is None

    finally:
        await engine.dispose()
