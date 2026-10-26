import asyncio
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from ops_pilot.models.incident import Incident


@pytest.mark.integration
def test_incident_row_lock_blocks_second_transaction() -> None:
    database_url = os.getenv("OPSPILOT_INTEGRATION_DATABASE_URL")
    incident_id_value = os.getenv("OPSPILOT_LOCK_TEST_INCIDENT_ID")

    if not database_url or not incident_id_value:
        pytest.skip("Dedicated integration database and test incident ID required")

    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Explicit dedicated-test-database confirmation required")

    incident_id = uuid.UUID(incident_id_value)

    async def scenario() -> None:
        engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
        )

        factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )

        try:
            async with factory() as first:
                async with factory() as second:
                    # Transaction 1 holds the incident row lock.
                    result = await first.execute(
                        select(Incident).where(Incident.id == incident_id).with_for_update()
                    )

                    incident = result.scalar_one_or_none()
                    assert incident is not None, "Test incident not found"

                    # Transaction 2 must not acquire the same
                    # lock while transaction 1 holds it.
                    with pytest.raises(DBAPIError) as exc_info:
                        await asyncio.wait_for(
                            second.execute(
                                select(Incident)
                                .where(Incident.id == incident_id)
                                .with_for_update(nowait=True)
                            ),
                            timeout=10,
                        )

                    error = exc_info.value
                    sqlstate = getattr(
                        error.orig,
                        "sqlstate",
                        None,
                    ) or getattr(
                        error.orig,
                        "pgcode",
                        None,
                    )

                    assert sqlstate == "55P03"

                    # Roll back both transactions.
                    await second.rollback()
                    await first.rollback()

        finally:
            await engine.dispose()

    asyncio.run(scenario())
