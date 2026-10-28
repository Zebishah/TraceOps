import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from ops_pilot.api.dependencies import (
    get_current_membership,
    get_current_user,
)
from ops_pilot.api.routes import incidents as incident_routes
from ops_pilot.core.exceptions import IncidentNotFoundError
from ops_pilot.db.session import get_db_session
from ops_pilot.main import app
from ops_pilot.models.incident import IncidentPriority, IncidentStatus
from ops_pilot.models.membership import MembershipRole
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
    IncidentClassification,
)
from ops_pilot.schemas.incidents import IncidentInvestigationResponse, IncidentResponse
from ops_pilot.schemas.retrieval import RetrievalResult

client = TestClient(app)

ORGANIZATION_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()


def make_incident(
    *,
    incident_id: uuid.UUID = INCIDENT_ID,
    organization_id: uuid.UUID = ORGANIZATION_ID,
):
    now = datetime.now(UTC)

    return SimpleNamespace(
        id=incident_id,
        organization_id=organization_id,
        created_by_user_id=USER_ID,
        title="Customer charged twice",
        description="Customer reports two charges for one order.",
        status=IncidentStatus.NEW,
        category=None,
        subject_customer_id=None,
        priority=None,
        created_at=now,
        updated_at=now,
    )


async def fake_db_session() -> AsyncMock:
    return AsyncMock()


async def fake_current_user():
    return SimpleNamespace(
        id=USER_ID,
    )


async def fake_membership():
    return SimpleNamespace(
        organization_id=ORGANIZATION_ID,
        user_id=USER_ID,
        role=MembershipRole.ADMIN,
    )


def set_authenticated_dependencies() -> None:
    app.dependency_overrides[get_db_session] = fake_db_session
    app.dependency_overrides[get_current_user] = fake_current_user
    app.dependency_overrides[get_current_membership] = fake_membership


def test_create_incident(monkeypatch) -> None:
    async def fake_create_incident(
        *,
        session,
        organization_id,
        user_id,
        payload,
    ):
        assert organization_id == ORGANIZATION_ID
        assert user_id == USER_ID
        assert payload.title == "Customer charged twice"

        return make_incident()

    monkeypatch.setattr(
        incident_routes,
        "create_incident",
        fake_create_incident,
    )

    set_authenticated_dependencies()

    try:
        response = client.post(
            f"/api/v1/organizations/{ORGANIZATION_ID}/incidents",
            json={
                "title": "Customer charged twice",
                "description": "Customer reports two charges for one order.",
            },
        )

        assert response.status_code == 201

        body = response.json()

        assert body["id"] == str(INCIDENT_ID)
        assert body["organization_id"] == str(ORGANIZATION_ID)
        assert body["created_by_user_id"] == str(USER_ID)
        assert body["status"] == "new"
        assert body["category"] is None
        assert body["priority"] is None

    finally:
        app.dependency_overrides.clear()


async def fake_list_incidents(
    *,
    session,
    organization_id,
    limit=50,
    offset=0,
):
    assert organization_id == ORGANIZATION_ID
    assert limit == 50
    assert offset == 0

    return [make_incident()]


def test_incident_pagination_forwards_parameters(monkeypatch) -> None:
    async def fake_list_incidents(
        *,
        session,
        organization_id,
        limit,
        offset,
    ):
        assert organization_id == ORGANIZATION_ID
        assert limit == 10
        assert offset == 20
        return [make_incident()]

    monkeypatch.setattr(
        incident_routes,
        "list_incidents",
        fake_list_incidents,
    )

    set_authenticated_dependencies()

    try:
        response = client.get(
            f"/api/v1/organizations/{ORGANIZATION_ID}/incidents",
            params={"limit": 10, "offset": 20},
        )

        assert response.status_code == 200
        assert len(response.json()) == 1

    finally:
        app.dependency_overrides.clear()


def test_incident_pagination_rejects_invalid_limits() -> None:
    set_authenticated_dependencies()

    try:
        path = f"/api/v1/organizations/{ORGANIZATION_ID}/incidents"

        for params in (
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
        ):
            response = client.get(path, params=params)
            assert response.status_code == 422

    finally:
        app.dependency_overrides.clear()


def test_get_incident(monkeypatch) -> None:
    async def fake_get_incident_response_cached(
        *,
        session,
        organization_id,
        incident_id,
        force_fresh=False,
    ):
        assert organization_id == ORGANIZATION_ID
        assert incident_id == INCIDENT_ID
        assert force_fresh is True
        return IncidentResponse.model_validate(make_incident())

    monkeypatch.setattr(
        incident_routes,
        "get_incident_response_cached",
        fake_get_incident_response_cached,
    )

    set_authenticated_dependencies()

    try:
        response = client.get(f"/api/v1/organizations/{ORGANIZATION_ID}/incidents/{INCIDENT_ID}")

        assert response.status_code == 200
        assert response.json()["id"] == str(INCIDENT_ID)
        assert response.json()["title"] == "Customer charged twice"

    finally:
        app.dependency_overrides.clear()


def test_get_incident_returns_404(
    monkeypatch,
) -> None:
    async def fake_get_incident_response_cached(
        *,
        session,
        organization_id,
        incident_id,
        force_fresh=False,
    ):
        assert force_fresh is True
        raise IncidentNotFoundError

    monkeypatch.setattr(
        incident_routes,
        "get_incident_response_cached",
        fake_get_incident_response_cached,
    )

    set_authenticated_dependencies()

    try:
        response = client.get(f"/api/v1/organizations/{ORGANIZATION_ID}/incidents/{INCIDENT_ID}")

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Incident not found",
        }

    finally:
        app.dependency_overrides.clear()


def test_incidents_require_organization_membership() -> None:
    fake_session = AsyncMock()

    result = Mock()
    result.scalar_one_or_none.return_value = None
    fake_session.execute.return_value = result

    async def override_db_session():
        return fake_session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_user] = fake_current_user

    try:
        response = client.get(f"/api/v1/organizations/{ORGANIZATION_ID}/incidents")

        assert response.status_code == 403
        assert response.json() == {
            "detail": "You do not have access to this organization",
        }

    finally:
        app.dependency_overrides.clear()


def test_classify_incident(monkeypatch) -> None:
    incident = make_incident()

    incident.status = IncidentStatus.INVESTIGATING
    incident.category = "payment"
    incident.priority = IncidentPriority.HIGH

    classification = IncidentClassification(
        category=IncidentCategory.PAYMENT,
        priority=IncidentPriority.HIGH,
        confidence=0.98,
    )

    async def fake_classify_stored_incident(
        *,
        session,
        organization_id,
        incident_id,
    ):
        assert organization_id == ORGANIZATION_ID
        assert incident_id == INCIDENT_ID

        return incident, classification

    monkeypatch.setattr(
        incident_routes,
        "classify_stored_incident",
        fake_classify_stored_incident,
    )

    set_authenticated_dependencies()

    try:
        response = client.post(
            f"/api/v1/organizations/{ORGANIZATION_ID}/incidents/{INCIDENT_ID}/classify"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["incident_id"] == str(INCIDENT_ID)
        assert body["status"] == "investigating"
        assert body["category"] == "payment"
        assert body["priority"] == "high"
        assert body["confidence"] == 0.98

    finally:
        app.dependency_overrides.clear()


def test_retrieve_incident_evidence(
    monkeypatch,
) -> None:
    evidence = RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=1,
        page_number=2,
        text="Duplicate payment cases require refund review.",
        source_filename="payments-policy.pdf",
        vector_score=0.81,
        reranker_score=0.95,
    )

    async def fake_retrieve_incident_evidence(
        *,
        session,
        organization_id,
        incident_id,
        limit=5,
    ):
        assert organization_id == ORGANIZATION_ID
        assert incident_id == INCIDENT_ID

        return (
            "Customer charged twice\n"
            "Customer was charged twice for one order.\n"
            "Incident category: payment",
            [evidence],
        )

    monkeypatch.setattr(
        incident_routes,
        "retrieve_incident_evidence",
        fake_retrieve_incident_evidence,
    )

    set_authenticated_dependencies()

    try:
        response = client.post(
            f"/api/v1/organizations/{ORGANIZATION_ID}/incidents/{INCIDENT_ID}/retrieve-evidence"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["incident_id"] == str(INCIDENT_ID)
        assert len(body["evidence"]) == 1

        assert body["evidence"][0]["source_filename"] == "payments-policy.pdf"

        assert body["evidence"][0]["reranker_score"] == 0.95

    finally:
        app.dependency_overrides.clear()


def test_investigate_incident(
    monkeypatch,
) -> None:
    evidence = RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=1,
        page_number=2,
        text="Duplicate payments require verification.",
        source_filename="payment-policy.pdf",
        vector_score=0.91,
        reranker_score=0.97,
    )

    async def fake_investigate_incident(
        *,
        session,
        organization_id,
        incident_id,
    ):
        assert organization_id == ORGANIZATION_ID
        assert incident_id == INCIDENT_ID

        return IncidentInvestigationResponse(
            organization_id=ORGANIZATION_ID,
            incident_id=INCIDENT_ID,
            workflow_thread_id="test-workflow-thread",
            title="Customer charged twice",
            description=("Two charges appeared for one order."),
            status=IncidentStatus.INVESTIGATING,
            category=IncidentCategory.PAYMENT,
            priority=IncidentPriority.HIGH,
            classification_confidence=0.98,
            retrieval_query=("Customer charged twice\nIncident category: payment"),
            evidence=[evidence],
            analysis=("The evidence supports a duplicate payment [SOURCE 1]."),
            recommended_action=("Verify both transaction IDs before refunding [SOURCE 1]."),
        )

    monkeypatch.setattr(
        incident_routes,
        "investigate_incident",
        fake_investigate_incident,
    )

    set_authenticated_dependencies()

    try:
        response = client.post(
            f"/api/v1/organizations/{ORGANIZATION_ID}/incidents/{INCIDENT_ID}/investigate"
        )

        assert response.status_code == 200

        body = response.json()

        assert body["incident_id"] == str(INCIDENT_ID)

        assert body["workflow_thread_id"] == "test-workflow-thread"

        assert body["category"] == "payment"
        assert body["priority"] == "high"

        assert body["classification_confidence"] == 0.98

        assert len(body["evidence"]) == 1

        assert body["evidence"][0]["source_filename"] == "payment-policy.pdf"

        assert "duplicate payment" in body["analysis"]

        assert "Verify both transaction IDs" in body["recommended_action"]

    finally:
        app.dependency_overrides.clear()
