import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from ops_pilot.api.dependencies import get_current_user
from ops_pilot.api.routes.dashboard import router
from ops_pilot.db.base import Base
from ops_pilot.db.session import get_db_session
from ops_pilot.models import (
    ApprovalRequest,
    ApprovalResumeJob,
    AutomationDelivery,
    BackgroundJob,
    Customer,
    Document,
    Incident,
    IncidentMemory,
    Membership,
    MembershipRole,
    OperationalOrder,
    Organization,
    PaymentTransaction,
    User,
)


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


@pytest_asyncio.fixture
async def dashboard_client():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    orgs = [uuid.uuid4(), uuid.uuid4()]
    users = [
        User(
            id=uuid.uuid4(),
            email=f"user{i}@example.test",
            full_name=f"User {i}",
            password_hash="not-a-real-hash",
            is_active=True,
        )
        for i in range(2)
    ]
    incidents = []
    docs = []
    with factory() as session:
        for index, org in enumerate(orgs):
            session.add(Organization(id=org, name=f"Team {index}", slug=f"team-{index}"))
            session.add(users[index])
            session.add(
                Membership(
                    id=uuid.uuid4(),
                    organization_id=org,
                    user_id=users[index].id,
                    role=MembershipRole.OWNER,
                )
            )
            customer = Customer(
                id=uuid.uuid4(),
                organization_id=org,
                external_customer_id=f"C-{index}",
                full_name=f"Customer {index}",
            )
            session.add(customer)
            incident = Incident(
                id=uuid.uuid4(),
                organization_id=org,
                created_by_user_id=users[index].id,
                subject_customer_id=customer.id,
                title="Charge_% review",
                description="Synthetic report",
                status="investigating",
            )
            session.add(incident)
            incidents.append(incident.id)
            document = Document(
                id=uuid.uuid4(),
                organization_id=org,
                uploaded_by_user_id=users[index].id,
                original_filename=f"policy-{index}.pdf",
                storage_key=f"private-storage-key-{index}",
                mime_type="application/pdf",
                size_bytes=100,
                checksum_sha256="a" * 64,
                status="ready",
            )
            session.add(document)
            docs.append(document.id)
            approval = ApprovalRequest(
                id=uuid.uuid4(),
                organization_id=org,
                incident_id=incident.id,
                workflow_thread_id=f"thread-{index}",
                action_type="refund_transaction",
                action_payload={"amount": "10.00"},
                reason="Synthetic approval",
                status="pending",
            )
            session.add(approval)
            session.add(
                ApprovalResumeJob(
                    id=uuid.uuid4(),
                    organization_id=org,
                    incident_id=incident.id,
                    approval_request_id=approval.id,
                    status="pending",
                    attempts=0,
                    next_attempt_at=datetime.now(UTC),
                )
            )
            session.add(
                BackgroundJob(
                    id=uuid.uuid4(),
                    organization_id=org,
                    created_by_user_id=users[index].id,
                    job_type="incident_analysis",
                    status="queued",
                    resource_id=incident.id,
                    idempotency_key=f"job-{index}",
                    progress_percent=0,
                )
            )
            session.add(
                AutomationDelivery(
                    id=uuid.uuid4(),
                    organization_id=org,
                    event_type="incident.high_risk",
                    webhook_path="private-webhook-path",
                    payload={"secret": "must-not-leak"},
                    status="retry",
                    attempt_count=1,
                    next_attempt_at=datetime.now(UTC),
                    last_error="HTTP error https://private.example/webhook/secret token=hidden",
                )
            )
            order = OperationalOrder(
                id=uuid.uuid4(),
                organization_id=org,
                customer_id=customer.id,
                external_order_id=f"ORDER-{index}",
                product_name="Sample",
                total_amount=10,
                currency="USD",
                status="paid",
                ordered_at=datetime.now(UTC),
            )
            session.add(order)
            session.add(
                PaymentTransaction(
                    id=uuid.uuid4(),
                    organization_id=org,
                    order_id=order.id,
                    external_transaction_id=f"TXN-{index}",
                    provider="simulation",
                    transaction_type="charge",
                    amount=10,
                    currency="USD",
                    status="succeeded",
                    payment_instrument_fingerprint="private-fingerprint",
                )
            )
            session.add(
                IncidentMemory(
                    id=uuid.uuid4(),
                    organization_id=org,
                    incident_id=incident.id,
                    subject_customer_id=customer.id,
                    category="payment",
                    summary="Synthetic historical summary",
                    resolution="Historical context only.",
                )
            )
        session.add(
            Incident(
                id=uuid.uuid4(),
                organization_id=orgs[0],
                created_by_user_id=users[0].id,
                title="Ordinary report",
                description="Another synthetic report",
                status="new",
            )
        )
        session.commit()

    # Exercise real SQL queries with SQLite, without a new async-driver dependency.
    # Concurrency/locking semantics remain covered by the PostgreSQL integration suite.
    class AsyncTestSession:
        def __init__(self, session):
            self.session = session

        async def execute(self, statement):
            return self.session.execute(statement)

        async def scalar(self, statement):
            return self.session.scalar(statement)

        async def get(self, model, identifier):
            return self.session.get(model, identifier)

        async def rollback(self):
            self.session.rollback()

    async def db():
        with factory() as session:
            yield AsyncTestSession(session)

    async def user():
        return users[0]

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = db
    app.dependency_overrides[get_current_user] = user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, orgs, incidents, docs, app
    engine.dispose()


@pytest.mark.asyncio
async def test_all_dashboard_collections_are_tenant_scoped(dashboard_client):
    client, orgs, *_ = dashboard_client
    for resource in [
        "incidents",
        "documents",
        "approvals",
        "jobs",
        "customers",
        "orders",
        "payments",
        "memories",
        "automations",
        "recovery",
    ]:
        response = await client.get(
            f"/api/v1/organizations/{orgs[0]}/dashboard/resources/{resource}"
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == (2 if resource == "incidents" else 1)
        assert all(row["organization_id"] == str(orgs[0]) for row in response.json()["items"])
        denied = await client.get(f"/api/v1/organizations/{orgs[1]}/dashboard/resources/{resource}")
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_foreign_resource_and_incident_cannot_be_discovered(dashboard_client):
    client, orgs, incidents, docs, _ = dashboard_client
    response = await client.get(
        f"/api/v1/organizations/{orgs[0]}/dashboard/resources/documents/{docs[1]}"
    )
    assert response.status_code == 404
    response = await client.get(
        f"/api/v1/organizations/{orgs[0]}/dashboard/incidents/{incidents[1]}/latest"
    )
    assert response.status_code == 404
    response = await client.get(
        f"/api/v1/organizations/{orgs[0]}/dashboard/incidents/{incidents[0]}/latest"
    )
    assert response.status_code == 200
    assert response.json()["job"]["organization_id"] == str(orgs[0])
    assert response.json()["approval"]["organization_id"] == str(orgs[0])


@pytest.mark.asyncio
async def test_overview_counts_only_selected_organization(dashboard_client):
    client, orgs, *_ = dashboard_client
    response = await client.get(f"/api/v1/organizations/{orgs[0]}/dashboard/overview")
    assert response.status_code == 200
    assert response.json()["incidents"] == 2
    assert response.json()["pending_approvals"] == 1
    assert response.json()["pending_automation"] == 1


@pytest.mark.asyncio
async def test_public_fields_do_not_expose_internal_secrets(dashboard_client):
    client, orgs, *_ = dashboard_client
    base = f"/api/v1/organizations/{orgs[0]}/dashboard/resources/"
    documents = (await client.get(base + "documents")).json()["items"]
    automation = (await client.get(base + "automations")).json()["items"]
    payments = (await client.get(base + "payments")).json()["items"]
    assert "storage_key" not in documents[0]
    assert "payload" not in automation[0]
    assert "lease_token" not in automation[0]
    assert "private.example" not in automation[0]["last_error"]
    assert "hidden" not in automation[0]["last_error"]
    assert "payment_instrument_fingerprint" not in payments[0]


@pytest.mark.asyncio
async def test_pagination_filters_and_literal_search(dashboard_client):
    client, orgs, *_ = dashboard_client
    base = f"/api/v1/organizations/{orgs[0]}/dashboard/resources/incidents"
    result = (await client.get(base + "?limit=1&offset=1")).json()
    assert result["total"] == 2
    assert len(result["items"]) == 1
    result = (await client.get(base, params={"q": "%"})).json()
    assert result["total"] == 1
    assert (await client.get(base + "?status=nonexistent")).status_code == 422
    assert (await client.get(base + "?limit=1000")).status_code == 422


@pytest.mark.asyncio
async def test_workspace_returns_configuration_without_credentials(dashboard_client):
    client, orgs, *_ = dashboard_client
    response = await client.get(f"/api/v1/organizations/{orgs[0]}/dashboard/workspace")
    assert response.status_code == 200
    assert response.json()["name"] == "Team 0"
    assert "groq_api_key" not in response.text
    assert "jwt_secret_key" not in response.text
    assert (
        await client.get(f"/api/v1/organizations/{orgs[1]}/dashboard/workspace")
    ).status_code == 403


@pytest.mark.asyncio
async def test_authentication_is_required(dashboard_client):
    client, orgs, _, _, app = dashboard_client
    app.dependency_overrides.pop(get_current_user)
    response = await client.get(f"/api/v1/organizations/{orgs[0]}/dashboard/overview")
    assert response.status_code in {401, 403}
