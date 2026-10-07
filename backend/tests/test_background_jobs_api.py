import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ops_pilot.api.dependencies import (
    get_current_membership,
    get_current_user,
)
from ops_pilot.api.routes import (
    background_jobs as background_job_routes,
)
from ops_pilot.db.session import get_db_session
from ops_pilot.main import app
from ops_pilot.models.background_job import (
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.schemas.background_jobs import (
    BackgroundJobResponse,
)

client = TestClient(app)

ORGANIZATION_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()


async def fake_db_session():
    return SimpleNamespace()


async def fake_current_user():
    return SimpleNamespace(
        id=USER_ID,
    )


async def fake_membership():
    return SimpleNamespace(
        organization_id=ORGANIZATION_ID,
        user_id=USER_ID,
    )


def set_authenticated_dependencies() -> None:
    app.dependency_overrides[get_db_session] = fake_db_session

    app.dependency_overrides[get_current_user] = fake_current_user

    app.dependency_overrides[get_current_membership] = fake_membership


def make_job_response() -> BackgroundJobResponse:
    now = datetime.now(
        UTC,
    )

    return BackgroundJobResponse(
        id=JOB_ID,
        organization_id=ORGANIZATION_ID,
        created_by_user_id=USER_ID,
        job_type=(BackgroundJobType.DOCUMENT_PROCESSING),
        status=BackgroundJobStatus.PROCESSING,
        resource_id=DOCUMENT_ID,
        progress_percent=60,
        error_message=None,
        created_at=now,
        started_at=now,
        completed_at=None,
        updated_at=now,
    )


def test_get_background_job(
    monkeypatch,
) -> None:
    expected = make_job_response()

    async def fake_get_background_job(
        **kwargs: object,
    ) -> BackgroundJobResponse:
        return expected

    monkeypatch.setattr(
        background_job_routes,
        "get_background_job",
        fake_get_background_job,
    )

    set_authenticated_dependencies()

    try:
        response = client.get(f"/api/v1/organizations/{ORGANIZATION_ID}/jobs/{JOB_ID}")

        assert response.status_code == 200

        body = response.json()

        assert body["id"] == str(JOB_ID)

        assert body["status"] == "processing"

        assert body["progress_percent"] == 60

    finally:
        app.dependency_overrides.clear()


def test_get_background_job_returns_404(
    monkeypatch,
) -> None:
    async def fake_get_background_job(
        **kwargs: object,
    ) -> None:
        return None

    monkeypatch.setattr(
        background_job_routes,
        "get_background_job",
        fake_get_background_job,
    )

    set_authenticated_dependencies()

    try:
        response = client.get(f"/api/v1/organizations/{ORGANIZATION_ID}/jobs/{JOB_ID}")

        assert response.status_code == 404

        assert response.json() == {
            "detail": "Background job not found",
        }

    finally:
        app.dependency_overrides.clear()
