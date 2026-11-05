"""OTP SQL behavior, automatic delivery, account limits and session issuance."""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from ops_pilot.api import dependencies
from ops_pilot.api.routes import auth as routes
from ops_pilot.models.email_verification_token import EmailVerificationToken
from ops_pilot.services import auth_rate_limit
from ops_pilot.services import email_verification as verification
from ops_pilot.services import transactional_email as delivery
from ops_pilot.services.auth_rate_limit import AuthRateLimitExceeded, AuthRateLimitUnavailable
from tests import test_email_verification as legacy_verification

settings = legacy_verification.settings
storage = legacy_verification.storage


@pytest.fixture
def codes(storage, settings, monkeypatch):
    settings.jwt_secret_key = "test-only-otp-signing-key"
    send = AsyncMock()
    monkeypatch.setattr(delivery, "send_verification_code", send)
    values = iter([12345, 23456, 34567, 45678])
    monkeypatch.setattr(verification.secrets, "randbelow", lambda upper: next(values))
    storage.code_send = send
    return storage


def sent_code(codes, call=-1):
    return codes.code_send.await_args_list[call].kwargs["code"]


@pytest.mark.anyio
async def test_code_is_six_digits_keyed_per_delivery_and_single_use(codes):
    assert await verification.issue_verification_code(codes.session, codes.user)
    code = sent_code(codes)
    assert re.fullmatch(r"[0-9]{6}", code)
    row = codes.session.sync.scalar(select(EmailVerificationToken))
    assert row.token_hash != hashlib.sha256(code.encode()).hexdigest()
    assert code != row.token_hash
    assert row.token_hash == verification._code_digest(row.id, codes.user.email, code)
    assert row.expires_at <= datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
    assert await verification.verify_email_code(codes.session, codes.user.email.upper(), code)
    assert codes.user.email_verified_at is not None
    assert await verification.verify_email_code(codes.session, codes.user.email, code) is None


@pytest.mark.anyio
async def test_wrong_code_or_other_mailbox_never_verifies(codes):
    await verification.issue_verification_code(codes.session, codes.user)
    code = sent_code(codes)
    wrong = "000000" if code != "000000" else "000001"
    for email, value in [
        (codes.user.email, wrong),
        ("other@example.com", code),
        (codes.user.email, "12345"),
        (codes.user.email, "１２３４５６"),
    ]:
        assert await verification.verify_email_code(codes.session, email, value) is None
    assert codes.user.email_verified_at is None
    assert await verification.verify_email_code(codes.session, codes.user.email, code)


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["expired", "mailbox_changed", "inactive"])
async def test_invalid_account_or_expired_code_cannot_verify(codes, state):
    await verification.issue_verification_code(codes.session, codes.user)
    code = sent_code(codes)
    address = codes.user.email
    if state == "expired":
        codes.session.sync.scalar(select(EmailVerificationToken)).expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    elif state == "mailbox_changed":
        codes.user.email = "new@example.com"
    else:
        codes.user.is_active = False
    codes.session.sync.commit()
    assert await verification.verify_email_code(codes.session, address, code) is None
    assert codes.user.email_verified_at is None


@pytest.mark.anyio
async def test_failed_resend_preserves_original_code_and_success_invalidates_all(codes):
    await verification.issue_verification_code(codes.session, codes.user)
    original = sent_code(codes)
    codes.code_send.side_effect = delivery.EmailDeliveryError("Delivery failed")
    assert not await verification.issue_verification_code(codes.session, codes.user)
    failed = sent_code(codes)
    assert await verification.verify_email_code(codes.session, codes.user.email, failed) is None
    codes.code_send.side_effect = None
    assert await verification.issue_verification_code(codes.session, codes.user)
    newest = sent_code(codes)
    assert await verification.verify_email_code(codes.session, codes.user.email, original)
    assert await verification.verify_email_code(codes.session, codes.user.email, newest) is None
    assert all(
        row.consumed_at for row in codes.session.sync.scalars(select(EmailVerificationToken))
    )


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [AuthRateLimitExceeded(30), AuthRateLimitUnavailable()])
async def test_code_delivery_budget_fails_closed(codes, failure):
    codes.budget.side_effect = failure
    assert not await verification.issue_verification_code(codes.session, codes.user)
    codes.code_send.assert_not_awaited()


@pytest.fixture
def api(settings, monkeypatch):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    session = AsyncMock()
    app.dependency_overrides[dependencies.get_db_session] = lambda: session
    user = SimpleNamespace(id=uuid.uuid4())
    claim = AsyncMock(return_value=user)
    limit = AsyncMock()
    monkeypatch.setattr(routes, "verify_email_code", claim)
    monkeypatch.setattr(routes, "enforce_verification_claim_limit", limit)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, claim=claim, limit=limit)


def test_successful_code_returns_session_and_invalid_code_never_does(api):
    payload = {"email": "person@example.com", "code": "012345"}
    response = api.client.post("/api/v1/auth/verification/code", json=payload)
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert response.json()["access_token"]
    assert response.headers["cache-control"] == "no-store"
    assert api.limit.await_args.kwargs["email"] == payload["email"]
    api.claim.return_value = None
    response = api.client.post("/api/v1/auth/verification/code", json=payload)
    assert response.status_code == 400
    assert "access_token" not in response.json()
    assert api.client.get("/api/v1/auth/verification/code").status_code == 405


def test_rate_limit_and_disabled_feature_block_code_claims(api, settings):
    payload = {"email": "person@example.com", "code": "012345"}
    api.limit.side_effect = AuthRateLimitExceeded(600)
    response = api.client.post("/api/v1/auth/verification/code", json=payload)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"
    api.claim.assert_not_awaited()
    settings.email_verification_enabled = False
    assert api.client.post("/api/v1/auth/verification/code", json=payload).status_code == 503
    api.claim.assert_not_awaited()


@pytest.mark.anyio
async def test_code_attempts_are_limited_across_peers_and_resends(monkeypatch):
    limit = AsyncMock()
    monkeypatch.setattr(auth_rate_limit, "_enforce_limit", limit)
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.10"))
    await auth_rate_limit.enforce_verification_claim_limit(
        request=request, email=" PERSON@Example.com "
    )
    assert limit.await_args.kwargs == {
        "category": "verification-code-account",
        "identifier": "person@example.com",
        "attempts": 5,
        "window_seconds": 600,
    }


@pytest.mark.anyio
async def test_code_email_contains_code_and_no_verification_link(settings, monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=httpx.Response(200, json={"id": "provider-id"}))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(delivery.httpx, "AsyncClient", lambda **kwargs: context)
    await delivery.send_verification_code(
        recipient="person@example.com", code="012345", minutes=10, delivery_id="id"
    )
    payload = client.post.await_args.kwargs["json"]
    assert "012345" in payload["text"] and "012345" in payload["html"]
    assert "10 minutes" in payload["text"]
    assert "#token=" not in payload["html"]
    assert payload["to"] == ["person@example.com"]
