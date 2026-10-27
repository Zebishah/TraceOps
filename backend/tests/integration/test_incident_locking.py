"""Verify PostgreSQL incident row locking with isolated test data."""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.models.organization import Organization
from ops_pilot.models.user import User


@pytest.mark.integration
def test_incident_row_lock_blocks_second_transaction() -> None:
    database_url = os.getenv("OPSPILOT_INTEGRATION_DATABASE_URL")

    if not database_url:
        pytest.skip("OPSPILOT_INTEGRATION_DATABASE_URL required")

    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Dedicated test database confirmation required")

    parsed = make_url(database_url)

    if parsed.get_backend_name() != "postgresql":
        pytest.fail("PostgreSQL is required")

    if not parsed.host or not parsed.database:
        pytest.fail("Valid test database connection required")

    real_url = os.getenv("OPSPILOT_REAL_DATABASE_URL")

    if real_url:
        real = make_url(real_url)
        if (
            parsed.host,
            parsed.port,
            parsed.database,
            parsed.username,
        ) == (
            real.host,
            real.port,
            real.database,
            real.username,
        ):
            pytest.fail("Refusing to use the real database")

    asyncio.run(_run_incident_lock_test(database_url))


async def _run_incident_lock_test(database_url: str) -> None:
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )

    factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    unique_key = uuid.uuid4().hex

    try:
        async with factory() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name="Incident Lock Test",
                    slug=f"incident-lock-{unique_key}",
                )
            )

            session.add(
                User(
                    id=user_id,
                    email=f"incident-lock-{unique_key}@example.com",
                    full_name="Incident Lock Test Reviewer",
                    password_hash="not-a-real-login",
                )
            )

            await session.flush()

            session.add(
                Incident(
                    id=incident_id,
                    organization_id=organization_id,
                    created_by_user_id=user_id,
                    title="PostgreSQL row-lock test",
                    description="Isolated synthetic incident",
                    status=IncidentStatus.INVESTIGATING,
                )
            )

            await session.commit()

        async with factory() as first:
            async with factory() as second:
                # Transaction 1 acquires the row lock.
                result = await first.execute(
                    select(Incident).where(Incident.id == incident_id).with_for_update()
                )

                locked_incident = result.scalar_one_or_none()
                assert locked_incident is not None

                try:
                    # Transaction 2 must fail immediately.
                    with pytest.raises(DBAPIError) as exc_info:
                        await asyncio.wait_for(
                            second.execute(
                                select(Incident)
                                .where(Incident.id == incident_id)
                                .with_for_update(nowait=True)
                            ),
                            timeout=15,
                        )

                    error = exc_info.value
                    sqlstate = getattr(error.orig, "sqlstate", None) or getattr(
                        error.orig, "pgcode", None
                    )

                    assert sqlstate == "55P03"

                finally:
                    await second.rollback()
                    await first.rollback()

    finally:
        try:
            async with factory() as session:
                await session.execute(
                    delete(Incident).where(
                        Incident.id == incident_id,
                        Incident.organization_id == organization_id,
                    )
                )

                await session.execute(
                    delete(Organization).where(
                        Organization.id == organization_id,
                    )
                )

                await session.execute(
                    delete(User).where(
                        User.id == user_id,
                    )
                )

                await session.commit()
        finally:
            await engine.dispose()
