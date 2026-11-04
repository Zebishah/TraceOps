import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from ops_pilot.api.dependencies import get_current_membership, get_current_user
from ops_pilot.api.routes import training
from ops_pilot.api.training_limit import TrainingBodyLimitMiddleware
from ops_pilot.db.base import Base
from ops_pilot.db.session import get_db_session
from ops_pilot.models import Membership, MembershipRole, TrainingControl, TrainingRun, User
from ops_pilot.services import training_runs

TOKEN = "synthetic-training-worker-key-1234567890"
ORG = uuid.uuid4()
OTHER = uuid.uuid4()
USER = uuid.uuid4()


@compiles(JSONB, "sqlite")
def sqlite_json(_type, _compiler, **kwargs):
    return "JSON"


@pytest_asyncio.fixture
async def training_client(monkeypatch):
    settings = SimpleNamespace(
        training_enabled=True,
        training_qlora_enabled=True,
        training_worker_token=SimpleNamespace(get_secret_value=lambda: TOKEN),
        training_max_runtime_seconds=5400,
    )
    monkeypatch.setattr(training, "get_settings", lambda: settings)
    monkeypatch.setattr(training_runs, "get_settings", lambda: settings)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(TrainingControl(id=1))
        session.commit()
    role = [MembershipRole.OWNER]

    class AsyncSession:
        def __init__(self, session):
            self.session = session

        async def execute(self, statement):
            return self.session.execute(statement)

        async def scalar(self, statement):
            return self.session.scalar(statement)

        async def get(self, model, key):
            return self.session.get(model, key)

        def add(self, value):
            self.session.add(value)

        async def commit(self):
            self.session.commit()

        async def rollback(self):
            self.session.rollback()

        async def refresh(self, value):
            self.session.refresh(value)

    async def db():
        with factory() as session:
            yield AsyncSession(session)

    async def user():
        return User(
            id=USER,
            email="fixture@example.test",
            full_name="Fixture",
            is_active=True,
            password_hash="test",
        )

    async def membership():
        return Membership(id=uuid.uuid4(), user_id=USER, organization_id=ORG, role=role[0])

    storage = {}

    class Storage:
        bucket_name = "private-test-bucket"
        client = SimpleNamespace(
            generate_presigned_url=lambda *a, **kw: "https://example.test/signed-adapter.zip"
        )

        async def upload_file(self, *, file, key, content_type):
            storage[key] = file.read()

        async def delete_file(self, *, key):
            storage.pop(key, None)

    monkeypatch.setattr(training, "S3Storage", Storage)
    app = FastAPI()
    app.add_middleware(TrainingBodyLimitMiddleware)
    app.include_router(training.router, prefix="/api/v1")
    app.include_router(training.worker_router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = db
    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_current_membership] = membership
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory, settings, role, storage
    engine.dispose()


def request_body(**changes):
    records = [
        {
            "title": f"Case {i}",
            "description": f"Synthetic test issue {i}",
            "category": "payment",
            "priority": "high",
            "group_id": f"group-{i}",
        }
        for i in range(6)
    ]
    return {
        "request_id": str(uuid.uuid4()),
        "name": "Synthetic adapter",
        "deidentified": True,
        "labels_reviewed": True,
        "dataset_jsonl": "\n".join(json.dumps(row) for row in records),
        **changes,
    }


def path(suffix="", org=ORG):
    return f"/api/v1/organizations/{org}/training{suffix}"


def worker_headers(lease=None):
    return {"Authorization": "Bearer " + TOKEN, **({"X-Training-Lease": lease} if lease else {})}


@pytest.mark.asyncio
async def test_training_lifecycle_and_tenant_isolation(training_client):
    client, factory, _, _, storage = training_client
    body = request_body()
    created = await client.post(path("/runs"), json=body)
    assert created.status_code == 202
    run = created.json()
    identifier = run["id"]
    assert run["status"] == "queued" and run["production_approved"] is False
    assert "examples" not in created.text and "dataset_jsonl" not in created.text
    assert created.headers["cache-control"] == "no-store"
    duplicate = await client.post(path("/runs"), json=body)
    assert duplicate.json()["id"] == identifier
    assert (await client.post(path("/runs"), json={**body, "name": "Changed"})).status_code == 409
    assert (await client.post(path("/runs"), json=request_body())).status_code == 409
    assert (await client.get(path(f"/runs/{identifier}", org=OTHER))).status_code == 404
    assert (await client.get(path("/runs", org=OTHER))).json()["items"] == []
    assert (await client.post(path(f"/runs/{identifier}/cancel", org=OTHER))).status_code == 404
    claimed = await client.post(
        "/api/v1/internal/training/claim", headers=worker_headers(), json={"device": "cpu"}
    )
    job = claimed.json()["job"]
    lease = job["lease_token"]
    assert job["id"] == identifier and len(job["payload"]["examples"]) == 6
    assert (
        await client.post(
            "/api/v1/internal/training/claim", headers=worker_headers(), json={"device": "cpu"}
        )
    ).json()["job"] is None
    heartbeat = f"/api/v1/internal/training/runs/{identifier}/heartbeat"
    assert (
        await client.post(
            heartbeat, headers=worker_headers(str(uuid.uuid4())), json={"stage": "training"}
        )
    ).status_code == 409
    assert (
        await client.post(
            heartbeat,
            headers=worker_headers(lease),
            json={"stage": "training", "completed_steps": 4, "epoch": 1},
        )
    ).status_code == 200
    assert (
        await client.post(
            heartbeat,
            headers=worker_headers(lease),
            json={"stage": "training", "completed_steps": 3},
        )
    ).status_code == 422
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("artifact.json", '{"test":true}')
    uploaded = await client.put(
        f"/api/v1/internal/training/runs/{identifier}/artifact",
        headers=worker_headers(lease),
        content=archive.getvalue(),
    )
    assert uploaded.status_code == 200 and storage
    metrics = {
        "total": 2,
        "category_accuracy": 0.5,
        "priority_accuracy": 1,
        "joint_accuracy": 0.5,
        "invalid_outputs": 0,
        "infrastructure_errors": 0,
        "critical_misses": 0,
        "high_risk_downgrades": 0,
    }
    finished = await client.post(
        f"/api/v1/internal/training/runs/{identifier}/finish",
        headers=worker_headers(lease),
        json={"status": "succeeded", "metrics": metrics},
    )
    assert finished.status_code == 200 and finished.json()["status"] == "succeeded"
    assert finished.json()["artifact_bytes"] == len(archive.getvalue())
    assert finished.json()["metrics"]["joint_accuracy"] == 0.5
    assert (await client.get(path(f"/runs/{identifier}/download"))).json()["expires_in"] == 60
    assert (await client.get(path(f"/runs/{identifier}/download", org=OTHER))).status_code == 404
    assert (
        await client.post(
            heartbeat,
            headers=worker_headers(lease),
            json={"stage": "training", "completed_steps": 5},
        )
    ).status_code == 409
    with factory() as session:
        assert session.scalar(select(TrainingRun)).dataset


@pytest.mark.asyncio
async def test_cancellation_retry_and_lease_expiry(training_client):
    client, factory, _, _, _ = training_client
    original = (await client.post(path("/runs"), json=request_body())).json()["id"]
    assert (await client.post(path(f"/runs/{original}/cancel"))).json()["status"] == "cancelled"
    retry = await client.post(
        path(f"/runs/{original}/retry"), json={"request_id": str(uuid.uuid4())}
    )
    run_id = retry.json()["id"]
    assert run_id != original
    job = (
        await client.post(
            "/api/v1/internal/training/claim", headers=worker_headers(), json={"device": "cpu"}
        )
    ).json()["job"]
    assert job["id"] == run_id
    assert (await client.post(path(f"/runs/{run_id}/cancel"))).json()[
        "status"
    ] == "cancel_requested"
    heartbeat = await client.post(
        f"/api/v1/internal/training/runs/{run_id}/heartbeat",
        headers=worker_headers(job["lease_token"]),
        json={"stage": "loading"},
    )
    assert heartbeat.json()["cancel_requested"] is True
    finished = await client.post(
        f"/api/v1/internal/training/runs/{run_id}/finish",
        headers=worker_headers(job["lease_token"]),
        json={"status": "succeeded"},
    )
    assert finished.json()["status"] == "cancelled"
    new = (await client.post(path("/runs"), json=request_body())).json()["id"]
    claimed = (
        await client.post(
            "/api/v1/internal/training/claim", headers=worker_headers(), json={"device": "cpu"}
        )
    ).json()["job"]
    with factory() as session:
        run = session.get(TrainingRun, uuid.UUID(new))
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    expired = await client.get(path(f"/runs/{new}"))
    assert (
        expired.json()["status"] == "failed"
        and expired.json()["error_code"] == "worker_lease_expired"
    )
    assert (
        await client.post(
            f"/api/v1/internal/training/runs/{new}/finish",
            headers=worker_headers(claimed["lease_token"]),
            json={"status": "failed"},
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_worker_auth_permissions_and_hardware(training_client):
    client, _, settings, role, _ = training_client
    for value in [MembershipRole.OPERATOR, MembershipRole.VIEWER, MembershipRole.REVIEWER]:
        role[0] = value
        assert (await client.get(path("/capabilities"))).status_code == 403
        assert (await client.post(path("/runs"), json=request_body())).status_code == 403
    role[0] = MembershipRole.OWNER
    assert (
        await client.post("/api/v1/internal/training/claim", json={"device": "cpu"})
    ).status_code == 401
    settings.training_qlora_enabled = False
    assert (await client.post(path("/runs"), json=request_body(method="qlora"))).status_code == 422
    settings.training_qlora_enabled = True
    await client.post(path("/runs"), json=request_body(method="qlora"))
    assert (
        await client.post(
            "/api/v1/internal/training/claim", headers=worker_headers(), json={"device": "cpu"}
        )
    ).json()["job"] is None
    assert (
        await client.post(
            "/api/v1/internal/training/claim", headers=worker_headers(), json={"device": "cuda"}
        )
    ).json()["job"] is not None
    settings.training_enabled = False
    assert (await client.get(path("/capabilities"))).json()["enabled"] is False
    assert (await client.get(path("/runs"))).status_code == 503


@pytest.mark.asyncio
async def test_dataset_validation_and_raw_body_cap(training_client):
    client, *_ = training_client
    assert (
        await client.post(path("/runs"), json=request_body(dataset_jsonl='{"title":"bad"}'))
    ).status_code == 422
    assert (
        await client.post(path("/runs"), json=request_body(labels_reviewed=False))
    ).status_code == 422
    assert (
        await client.post(
            path("/runs"),
            content=b"x" * (512 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        )
    ).status_code == 413
    assert (
        await client.post(path("/runs"), json=request_body(model_id="arbitrary/model"))
    ).status_code == 422
