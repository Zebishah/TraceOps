"""Real row-lock admission and worker claim tests against a disposable CI database."""

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ops_pilot.models import Organization, TrainingRun, User
from ops_pilot.schemas.training import TrainingConfig
from ops_pilot.services import training_runs

pytestmark = pytest.mark.skipif(
    not os.getenv("TRAINING_TEST_DATABASE_URL"),
    reason="Disposable training PostgreSQL database not configured",
)


@pytest.mark.asyncio
async def test_concurrent_admission_and_claim_are_serialized(monkeypatch):
    engine = create_async_engine(os.environ["TRAINING_TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    org, user = uuid.uuid4(), uuid.uuid4()
    settings = SimpleNamespace(
        training_enabled=True, training_qlora_enabled=True, training_max_runtime_seconds=5400
    )
    monkeypatch.setattr(training_runs, "get_settings", lambda: settings)
    try:
        async with factory() as session:
            session.add(
                Organization(id=org, name="Training concurrency fixture", slug=f"training-{org}")
            )
            session.add(
                User(
                    id=user,
                    email=f"{user}@example.test",
                    full_name="Fixture",
                    is_active=True,
                    password_hash="fixture",
                )
            )
            await session.commit()
        examples = [
            dict(
                title=f"Fixture {n}",
                description=f"Synthetic case {n}",
                category="payment",
                priority="high",
                group_id=f"case-{n}",
            )
            for n in range(6)
        ]
        import json

        request = TrainingConfig(
            request_id=uuid.uuid4(),
            name="Concurrent fixture",
            deidentified=True,
            labels_reviewed=True,
            dataset_jsonl="\n".join(json.dumps(row) for row in examples),
        )
        payload = training_runs.normalize_dataset(request)

        async def create():
            async with factory() as session:
                return await training_runs.create_run(
                    session, org=org, user=user, request_id=request.request_id, payload=payload
                )

        first, second = await asyncio.gather(create(), create())
        assert first.id == second.id

        async def claim():
            async with factory() as session:
                return await training_runs.claim(session, "cpu")

        claims = await asyncio.gather(claim(), claim())
        assert sum(value is not None for value in claims) == 1
        claimed = next(value for value in claims if value is not None)
        assert claimed["id"] == str(first.id)
        async with factory() as session:
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as caught:
                await training_runs.leased_run(session, first.id, uuid.uuid4())
            assert caught.value.status_code == 409
    finally:
        async with factory() as session:
            await session.execute(delete(TrainingRun).where(TrainingRun.organization_id == org))
            await session.execute(delete(Organization).where(Organization.id == org))
            await session.execute(delete(User).where(User.id == user))
            await session.commit()
        await engine.dispose()
