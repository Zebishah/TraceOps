"""Real session events cover commits, context managers, bulk SQL and rollbacks."""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError

from ops_pilot.db import cache_session
from ops_pilot.models import Incident, Organization, User


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    for model in [Organization, User, Incident]:
        model.__table__.create(engine)
    invalidate = AsyncMock()
    monkeypatch.setattr(cache_session, "invalidate_dashboard_cache", invalidate)
    yield engine, invalidate
    engine.dispose()


def session_for(engine):
    # SQLite runs synchronously here; real AsyncSession transactions/events still execute.
    session = cache_session.DashboardSession(expire_on_commit=False)
    session.sync_session.bind = engine
    return session


async def seed(session):
    org, user = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            Organization(id=org, name="Team", slug=str(org)),
            User(id=user, email=f"{user}@example.com", full_name="Owner", password_hash="test"),
        ]
    )
    await session.commit()
    return org, user


@pytest.mark.anyio
async def test_commits_invalidate_tenant_after_data_is_visible_and_readonly_commits_do_not(
    database,
):
    engine, invalidate = database
    async with session_for(engine) as session:
        org, user = await seed(session)
        invalidate.reset_mock()
        incident = Incident(
            organization_id=org, created_by_user_id=user, title="New", description="Test"
        )
        session.add(incident)
        await session.commit()
        invalidate.assert_awaited_once_with({str(org)})
        invalidate.reset_mock()
        await session.execute(select(Incident))
        await session.commit()
        invalidate.assert_not_awaited()


@pytest.mark.anyio
async def test_context_manager_and_savepoint_commit_wait_until_root_commit(database):
    engine, invalidate = database
    async with session_for(engine) as session:
        org, user = await seed(session)
        invalidate.reset_mock()
        async with session.begin():
            session.add(
                Incident(
                    organization_id=org, created_by_user_id=user, title="New", description="Test"
                )
            )
            async with session.begin_nested():
                invalidate.assert_not_awaited()
            invalidate.assert_not_awaited()
        invalidate.assert_awaited_once_with({str(org)})


@pytest.mark.anyio
async def test_rollback_and_failed_commit_never_invalidate(database):
    engine, invalidate = database
    async with session_for(engine) as session:
        org, user = await seed(session)
        invalidate.reset_mock()
        session.add(
            Incident(organization_id=org, created_by_user_id=user, title="New", description="Test")
        )
        await session.flush()
        await session.rollback()
        await session.commit()
        invalidate.assert_not_awaited()
        session.add(Organization(id=uuid.uuid4(), name="Duplicate", slug=str(org)))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        await session.commit()
        invalidate.assert_not_awaited()


@pytest.mark.anyio
async def test_bulk_worker_updates_rotate_global_namespace_after_commit(database):
    engine, invalidate = database
    async with session_for(engine) as session:
        org, user = await seed(session)
        session.add(
            Incident(organization_id=org, created_by_user_id=user, title="New", description="Test")
        )
        await session.commit()
        invalidate.reset_mock()
        async with session.begin():
            await session.execute(
                update(Incident)
                .where(Incident.organization_id == org)
                .values(status="investigating")
            )
            invalidate.assert_not_awaited()
        invalidate.assert_awaited_once_with({"*"})


@pytest.mark.anyio
async def test_bulk_rollback_and_tenant_changes_are_handled(database):
    engine, invalidate = database
    async with session_for(engine) as session:
        org, user = await seed(session)
        next_org = uuid.uuid4()
        session.add(Organization(id=next_org, name="Next", slug=str(next_org)))
        incident = Incident(
            organization_id=org, created_by_user_id=user, title="New", description="Test"
        )
        session.add(incident)
        await session.commit()
        invalidate.reset_mock()
        await session.execute(update(Incident).values(status="failed"))
        await session.rollback()
        await session.commit()
        invalidate.assert_not_awaited()
        await session.refresh(incident)
        incident.organization_id = next_org
        await session.commit()
        invalidate.assert_awaited_once_with({str(org), str(next_org)})
