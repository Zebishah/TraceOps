"""Exercise real SQL claims, delivery failure recovery, and REST/MCP verification gates."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ops_pilot.api import dependencies
from ops_pilot.api.routes import auth as routes
from ops_pilot.core.config import Settings
from ops_pilot.core.security import create_access_token
from ops_pilot.models.email_verification_token import EmailVerificationToken
from ops_pilot.models.user import User
from ops_pilot.services import email_verification as verification
from ops_pilot.services import transactional_email as delivery
from ops_pilot.services.auth_rate_limit import AuthRateLimitExceeded, AuthRateLimitUnavailable


class AsyncSQLiteSession:
    """Run service SQL against SQLite without adding a test dependency."""

    def __init__(self, session):
        self.sync = session

    async def scalar(self, statement):
        return self.sync.scalar(statement)

    async def execute(self, statement):
        return self.sync.execute(statement)

    async def get(self, model, identifier):
        return self.sync.get(model, identifier)

    def add(self, instance):
        self.sync.add(instance)

    async def commit(self):
        self.sync.commit()

    async def rollback(self):
        self.sync.rollback()


@pytest.fixture
def settings(monkeypatch):
    value = SimpleNamespace(
        email_verification_enabled=True,
        email_verification_expire_minutes=60,
        email_verification_daily_limit=80,
        frontend_base_url="https://workspace.example",
        resend_api_key=SecretStr("re_test_only_never_real"),
        email_from="OpsPilot <opspilot@example.com>",
        email_delivery_timeout_seconds=10,
    )
    monkeypatch.setattr(verification, "get_settings", lambda: value)
    monkeypatch.setattr(routes, "get_settings", lambda: value)
    monkeypatch.setattr(delivery, "get_settings", lambda: value)
    return value


@pytest.fixture
def storage(settings, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    User.__table__.create(engine)
    EmailVerificationToken.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as sync:
        user = User(
            id=uuid.uuid4(),
            email="person@example.com",
            full_name="Demo user",
            password_hash="not-used-in-this-test",
            is_active=True,
        )
        sync.add(user)
        sync.commit()
        session = AsyncSQLiteSession(sync)
        send = AsyncMock()
        budget = AsyncMock()
        monkeypatch.setattr(verification, "send_verification_email", send)
        monkeypatch.setattr(verification, "enforce_verification_delivery_limit", budget)
        yield SimpleNamespace(session=session, user=user, send=send, budget=budget)
    engine.dispose()


def sent_token(storage, call=-1):
    return parse_qs(urlsplit(storage.send.await_args_list[call].kwargs["url"]).fragment)["token"][0]


@pytest.mark.anyio
async def test_delivery_stores_hash_and_uses_fragment_not_query(storage):
    assert await verification.issue_verification_email(storage.session, storage.user)
    raw = sent_token(storage)
    rows = storage.session.sync.scalars(select(EmailVerificationToken)).all()
    assert len(rows) == 1
    assert rows[0].token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert rows[0].token_hash != raw
    assert rows[0].email == storage.user.email
    link = storage.send.await_args.kwargs["url"]
    assert link.startswith("https://workspace.example/verify-email#token=")
    assert urlsplit(link).query == ""
    assert verification.requires_email_verification(storage.user)


@pytest.mark.anyio
async def test_valid_link_is_single_use_and_all_other_links_expire(storage):
    for _ in range(2):
        assert await verification.issue_verification_email(storage.session, storage.user)
    first, second = sent_token(storage, 0), sent_token(storage, 1)
    assert first != second
    assert await verification.verify_email_token(storage.session, first)
    assert storage.user.email_verified_at is not None
    assert not verification.requires_email_verification(storage.user)
    assert not await verification.verify_email_token(storage.session, first)
    assert not await verification.verify_email_token(storage.session, second)
    assert all(t.consumed_at for t in storage.session.sync.scalars(select(EmailVerificationToken)))


@pytest.mark.anyio
async def test_expired_link_cannot_verify(storage):
    await verification.issue_verification_email(storage.session, storage.user)
    raw = sent_token(storage)
    token = storage.session.sync.scalar(select(EmailVerificationToken))
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    storage.session.sync.commit()
    assert not await verification.verify_email_token(storage.session, raw)
    assert storage.user.email_verified_at is None


@pytest.mark.anyio
async def test_link_is_bound_to_original_mailbox(storage):
    await verification.issue_verification_email(storage.session, storage.user)
    raw = sent_token(storage)
    storage.user.email = "changed@example.com"
    storage.session.sync.commit()
    assert not await verification.verify_email_token(storage.session, raw)
    assert storage.user.email_verified_at is None


@pytest.mark.anyio
async def test_failed_resend_does_not_break_an_earlier_link(storage, caplog):
    await verification.issue_verification_email(storage.session, storage.user)
    original = sent_token(storage)
    storage.send.side_effect = delivery.EmailDeliveryError("provider error")
    assert not await verification.issue_verification_email(storage.session, storage.user)
    failed = sent_token(storage)
    assert not await verification.verify_email_token(storage.session, failed)
    assert await verification.verify_email_token(storage.session, original)
    assert original not in caplog.text and failed not in caplog.text
    assert storage.user.email not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "inactive,verified,enabled", [(True, False, True), (False, True, True), (False, False, False)]
)
async def test_unavailable_or_verified_accounts_receive_no_email(
    storage, settings, inactive, verified, enabled
):
    storage.user.is_active = not inactive
    storage.user.email_verified_at = datetime.now(UTC) if verified else None
    settings.email_verification_enabled = enabled
    assert not await verification.issue_verification_email(storage.session, storage.user)
    storage.send.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [AuthRateLimitExceeded(30), AuthRateLimitUnavailable()])
async def test_delivery_budget_fails_closed(storage, failure):
    storage.budget.side_effect = failure
    assert not await verification.issue_verification_email(storage.session, storage.user)
    storage.send.assert_not_awaited()
    assert storage.session.sync.scalar(select(EmailVerificationToken)) is None


@pytest.mark.anyio
async def test_disabled_user_cannot_claim_or_use_mcp(storage):
    await verification.issue_verification_email(storage.session, storage.user)
    raw = sent_token(storage)
    storage.user.is_active = False
    storage.session.sync.commit()
    assert not await verification.verify_email_token(storage.session, raw)
    assert not await verification.mcp_subject_allowed(storage.session, storage.user.id)


@pytest.mark.anyio
async def test_mcp_account_gate_checks_verified_user(storage):
    assert not await verification.mcp_subject_allowed(storage.session, storage.user.id)
    storage.user.email_verified_at = datetime.now(UTC)
    storage.session.sync.commit()
    assert await verification.mcp_subject_allowed(storage.session, storage.user.id)
    assert not await verification.mcp_subject_allowed(storage.session, uuid.uuid4())


@pytest.mark.anyio
async def test_disabled_feature_does_not_add_mcp_database_queries(settings):
    settings.email_verification_enabled = False
    session = AsyncMock()
    assert await verification.mcp_subject_allowed(session, uuid.uuid4())
    session.get.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("raw", ["", "wrong", "x" * 44, "é" * 43, "a" * 43])
async def test_invalid_or_unknown_proof_cannot_verify(storage, raw):
    assert not await verification.verify_email_token(storage.session, raw)
    assert storage.user.email_verified_at is None


@pytest.fixture
def api(settings, monkeypatch):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    session = AsyncMock()
    app.dependency_overrides[dependencies.get_db_session] = lambda: session
    user = SimpleNamespace(
        id=uuid.uuid4(),
        email="person@example.com",
        full_name="Demo user",
        is_active=True,
        email_verified_at=None,
    )
    auth = AsyncMock(return_value=user)
    issue = AsyncMock(return_value=True)
    lookup = AsyncMock(return_value=user)
    claim = AsyncMock(return_value=True)
    request_limit = AsyncMock()
    claim_limit = AsyncMock()
    monkeypatch.setattr(routes, "register_user", AsyncMock(return_value=user))
    monkeypatch.setattr(routes, "authenticate_user", auth)
    monkeypatch.setattr(routes, "issue_verification_email", issue)
    monkeypatch.setattr(routes, "get_user_by_email", lookup)
    monkeypatch.setattr(routes, "verify_email_token", claim)
    monkeypatch.setattr(routes, "enforce_registration_rate_limit", AsyncMock())
    monkeypatch.setattr(routes, "enforce_login_rate_limit", AsyncMock())
    monkeypatch.setattr(routes, "enforce_verification_request_limit", request_limit)
    monkeypatch.setattr(routes, "enforce_verification_claim_limit", claim_limit)
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            user=user,
            auth=auth,
            issue=issue,
            claim=claim,
            lookup=lookup,
            request_limit=request_limit,
            claim_limit=claim_limit,
            session=session,
        )


def test_registration_requires_verification_and_returns_delivery_state(api):
    body = {
        "email": api.user.email,
        "password": "test-password",
        "full_name": "Demo user",
        "organization_name": "Demo workspace",
        "organization_slug": "demo-workspace",
    }
    for sent in (True, False):
        api.issue.return_value = sent
        response = api.client.post("/api/v1/auth/register", json=body)
        assert response.status_code == 201
        assert response.json()["verification_required"] is True
        assert response.json()["verification_email_sent"] is sent
        assert response.json()["email_verified"] is False
        assert "access_token" not in response.json()
        assert response.headers["cache-control"] == "no-store"


def test_unverified_login_never_issues_a_session(api):
    response = api.client.post(
        "/api/v1/auth/login", json={"email": api.user.email, "password": "test-password"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "email_verification_required"
    assert "access_token" not in response.json()
    api.issue.assert_not_awaited()


def test_wrong_login_does_not_disclose_verification_state(api):
    api.auth.return_value = None
    response = api.client.post(
        "/api/v1/auth/login", json={"email": api.user.email, "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_verified_login_returns_a_session(api):
    api.user.email_verified_at = datetime.now(UTC)
    response = api.client.post(
        "/api/v1/auth/login", json={"email": api.user.email, "password": "test-password"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_resend_does_not_disclose_account_or_delivery_state(api):
    responses = []
    for user, sent in [(api.user, True), (api.user, False), (None, False)]:
        api.lookup.return_value = user
        api.issue.return_value = sent
        response = api.client.post(
            "/api/v1/auth/verification/request", json={"email": "person@example.com"}
        )
        assert response.status_code == 200
        responses.append(response.json())
    assert responses[0] == responses[1] == responses[2]
    assert api.issue.await_count == 2


@pytest.mark.parametrize(
    "error,status", [(AuthRateLimitExceeded(42), 429), (AuthRateLimitUnavailable(), 503)]
)
def test_resend_rate_limits_block_delivery(api, error, status):
    api.request_limit.side_effect = error
    response = api.client.post(
        "/api/v1/auth/verification/request", json={"email": "person@example.com"}
    )
    assert response.status_code == status
    if status == 429:
        assert response.headers["retry-after"] == "42"
    api.lookup.assert_not_awaited()
    api.issue.assert_not_awaited()


def test_verification_is_post_only_and_issues_no_session(api):
    assert api.client.get("/api/v1/auth/verification/confirm?token=" + "a" * 43).status_code == 405
    api.claim.assert_not_awaited()
    response = api.client.post("/api/v1/auth/verification/confirm", json={"token": "a" * 43})
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert "access_token" not in response.json()
    assert "set-cookie" not in response.headers
    api.claim.return_value = False
    assert (
        api.client.post("/api/v1/auth/verification/confirm", json={"token": "a" * 43}).status_code
        == 400
    )


def test_claim_rate_limit_runs_before_token_lookup(api):
    api.claim_limit.side_effect = AuthRateLimitExceeded(12)
    response = api.client.post("/api/v1/auth/verification/confirm", json={"token": "a" * 43})
    assert response.status_code == 429
    api.claim.assert_not_awaited()


def test_disabled_feature_keeps_existing_login_and_registration_behavior(api, settings):
    settings.email_verification_enabled = False
    response = api.client.post(
        "/api/v1/auth/login", json={"email": api.user.email, "password": "test-password"}
    )
    assert response.status_code == 200
    for suffix, payload in [
        ("request", {"email": api.user.email}),
        ("confirm", {"token": "a" * 43}),
    ]:
        assert (
            api.client.post("/api/v1/auth/verification/" + suffix, json=payload).status_code == 503
        )
    api.issue.assert_not_awaited()


@pytest.mark.anyio
async def test_existing_rest_token_cannot_bypass_email_gate(api):
    api.session.get.return_value = api.user
    token = create_access_token(subject=str(api.user.id))
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await dependencies.get_current_user(credentials, api.session)
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "email_verification_required"


@pytest.mark.parametrize(
    "changes",
    [
        {"resend_api_key": None},
        {"resend_api_key": ""},
        {"email_from": "invalid"},
        {"email_from": "test@example.com\r\nBcc: other@example.com"},
        {"frontend_base_url": None},
        {"frontend_base_url": "https://user:password@example.com"},
        {"frontend_base_url": "http://public.example"},
        {"frontend_base_url": "https://example.com/path"},
        {"frontend_base_url": "https://example.com?next=evil"},
    ],
)
def test_enabled_verification_requires_safe_configuration(changes):
    values = {
        "email_verification_enabled": True,
        "resend_api_key": "re_test_only",
        "email_from": "OpsPilot <sender@example.com>",
        "frontend_base_url": "https://workspace.example",
    }
    with pytest.raises(ValidationError):
        Settings(**(values | changes))


def test_config_accepts_local_development_and_masks_resend_key():
    settings = Settings(
        email_verification_enabled=True,
        resend_api_key="re_test_only_secret",
        email_from="OpsPilot <sender@example.com>",
        frontend_base_url="http://localhost:3000",
    )
    assert "re_test_only_secret" not in repr(settings)
    assert settings.email_verification_expire_minutes == 60


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, json={"message": "secret-provider-body"}),
        httpx.Response(429, json={"message": "quota"}),
        httpx.Response(200, json={}),
        httpx.Response(200, text="not-json"),
    ],
)
async def test_delivery_errors_never_expose_provider_data(settings, monkeypatch, response):
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(delivery.httpx, "AsyncClient", lambda **kwargs: context)
    with pytest.raises(delivery.EmailDeliveryError) as caught:
        await delivery.send_verification_email(
            recipient="person@example.com",
            url="https://workspace.example/verify-email#token=private",
            delivery_id="test-id",
        )
    assert "secret-provider-body" not in str(caught.value)
    assert "private" not in str(caught.value)


@pytest.mark.anyio
async def test_resend_request_uses_correct_payload_and_idempotency(settings, monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=httpx.Response(200, json={"id": "provider-message-id"}))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(delivery.httpx, "AsyncClient", lambda **kwargs: context)
    await delivery.send_verification_email(
        recipient="person@example.com",
        url="https://workspace.example/verify-email#token=private",
        delivery_id="test-id",
    )
    args = client.post.await_args
    assert args.args == ("https://api.resend.com/emails",)
    assert args.kwargs["headers"]["Idempotency-Key"] == "email-verification/test-id"
    assert args.kwargs["json"]["from"] == settings.email_from
    assert args.kwargs["json"]["to"] == ["person@example.com"]
    assert "#token=private" in args.kwargs["json"]["text"]
    assert "<script>" not in json.dumps(args.kwargs["json"])


@pytest.mark.anyio
async def test_mcp_access_token_verifiers_recheck_verification(api, settings, monkeypatch):
    from contextlib import asynccontextmanager

    from ops_pilot.core.config import get_settings
    from ops_pilot.core.security import create_mcp_access_token
    from ops_pilot.mcp import auth as mcp_auth
    from ops_pilot.mcp import oauth_provider

    config = get_settings().model_copy(update={"email_verification_enabled": True})
    session = AsyncMock()
    session.get.return_value = api.user

    @asynccontextmanager
    async def factory():
        yield session

    for module in (mcp_auth, oauth_provider):
        monkeypatch.setattr(module, "async_session_factory", factory)
        monkeypatch.setattr(module, "get_settings", lambda: config)
        monkeypatch.setattr(module, "is_mcp_access_token_revoked", AsyncMock(return_value=False))
    token = create_mcp_access_token(subject=str(api.user.id))
    verifier = mcp_auth.OpsPilotMCPTokenVerifier()
    provider = oauth_provider.OpsPilotOAuthProvider()
    assert await verifier.verify_token(token) is None
    assert await provider.load_access_token(token) is None
    api.user.email_verified_at = datetime.now(UTC)
    assert await verifier.verify_token(token) is not None
    assert await provider.load_access_token(token) is not None


@pytest.mark.anyio
async def test_refresh_exchange_rejects_unverified_account_before_rotation(monkeypatch):
    from mcp.server.auth.provider import RefreshToken, TokenError
    from mcp.shared.auth import OAuthClientInformationFull

    from ops_pilot.mcp import oauth_provider

    session = AsyncMock()

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)

    def factory():
        return context

    stored = SimpleNamespace(
        scopes="ops-pilot:read",
        user_id=uuid.uuid4(),
        resource="http://localhost:8000/mcp",
    )
    revoke = AsyncMock()
    create = AsyncMock()
    monkeypatch.setattr(oauth_provider, "async_session_factory", factory)
    monkeypatch.setattr(oauth_provider, "load_refresh_token", AsyncMock(return_value=stored))
    monkeypatch.setattr(oauth_provider, "mcp_subject_allowed", AsyncMock(return_value=False))
    monkeypatch.setattr(oauth_provider, "revoke_refresh_token", revoke)
    monkeypatch.setattr(oauth_provider, "create_refresh_token", create)
    client = OAuthClientInformationFull(
        client_id="test",
        redirect_uris=["https://client.example/callback"],
        token_endpoint_auth_method="none",
    )
    token = RefreshToken(token="refresh", client_id="test", scopes=["ops-pilot:read"])
    with pytest.raises(TokenError):
        await oauth_provider.OpsPilotOAuthProvider().exchange_refresh_token(client, token, [])
    revoke.assert_not_awaited()
    create.assert_not_awaited()
    session.commit.assert_not_awaited()
