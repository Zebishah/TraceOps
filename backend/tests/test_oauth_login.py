"""Browser consent contract, failure states and request-integrity regression tests."""

from contextlib import asynccontextmanager
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from ops_pilot.mcp import oauth_form, oauth_login
from ops_pilot.services.auth_rate_limit import AuthRateLimitExceeded, AuthRateLimitUnavailable

BASE = "https://ops.example"
CALLBACK = "https://client.example/callback"
PARAMS = {
    "client_id": "test-client",
    "redirect_uri": CALLBACK,
    "state": "state<&\"'",
    "scope": "ops-pilot:read",
    "code_challenge": "a" * 43,
    "resource": f"{BASE}/mcp",
    "redirect_uri_explicit": "true",
}


class HiddenFields(HTMLParser):
    def __init__(self, body: str):
        super().__init__(convert_charrefs=True)
        self.values = {}
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("type") == "hidden":
            self.values[attrs["name"]] = attrs["value"]


@pytest.fixture
def flow(monkeypatch):
    settings = SimpleNamespace(
        environment="production",
        jwt_secret_key="test-only-key-for-oauth-forms-1234567890",
        mcp_authorization_server_url=BASE,
        mcp_resource_url=f"{BASE}/mcp",
    )
    registered = SimpleNamespace(
        client_name='Demo AI <script>alert("client")</script>',
        scope="ops-pilot:read ops-pilot:write",
        redirect_uris_json=f'["{CALLBACK}"]',
    )
    session = object()

    @asynccontextmanager
    async def session_factory():
        yield session

    lookup = AsyncMock(return_value=registered)
    auth = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    rate = AsyncMock()
    code = AsyncMock(return_value="one-use-authorization-code")
    monkeypatch.setattr(oauth_login, "get_settings", lambda: settings)
    monkeypatch.setattr(oauth_login, "async_session_factory", session_factory)
    monkeypatch.setattr(oauth_login, "get_oauth_client", lookup)
    monkeypatch.setattr(oauth_login, "authenticate_user", auth)
    monkeypatch.setattr(oauth_login, "enforce_login_rate_limit", rate)
    monkeypatch.setattr(oauth_login, "create_authorization_code", code)
    app = Starlette(
        routes=[
            Route("/oauth/login", oauth_login.oauth_login_page, methods=["GET"]),
            Route("/oauth/login", oauth_login.oauth_login_submit, methods=["POST"]),
        ]
    )
    with TestClient(app, base_url=BASE, follow_redirects=False) as client:
        yield SimpleNamespace(
            client=client,
            app=app,
            auth=auth,
            rate=rate,
            code=code,
            lookup=lookup,
            registered=registered,
            session=session,
            settings=settings,
        )


def open_form(flow, **changes):
    response = flow.client.get("/oauth/login", params=PARAMS | changes)
    assert response.status_code == 200
    return response, HiddenFields(response.text).values


def submit(flow, fields, **changes):
    return flow.client.post(
        "/oauth/login",
        data=fields
        | {"email": "user@example.com", "password": "test-password", "decision": "allow"}
        | changes,
        headers={"Origin": BASE},
    )


def test_page_explains_real_permissions_and_escapes_client(flow):
    response, fields = open_form(flow)
    assert fields.keys() == {*PARAMS, "csrf_token"}
    assert fields["state"] == PARAMS["state"]
    assert "Read workspace context" in response.text
    assert "Investigate and request actions" not in response.text
    assert "&lt;script&gt;" in response.text
    assert '<script>alert("client")</script>' not in response.text
    assert CALLBACK not in response.text.split("<code>")[1].split("</code>")[0]
    assert "https://client.example</code>" in response.text
    assert "Application names are supplied by the connecting app" in response.text
    assert "https://fonts" not in response.text
    assert 'id="page-title"' in response.text
    cookie = response.headers["set-cookie"]
    for flag in ("__Host-opspilot_oauth_browser=", "HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self' https://client.example" in csp
    assert "'nonce-" in csp
    flow.auth.assert_not_awaited()


def test_write_access_is_shown_only_when_requested(flow):
    response, _ = open_form(flow, scope="ops-pilot:read ops-pilot:write")
    assert "Investigate and request actions" in response.text
    assert "Sensitive actions still require human approval" in response.text


@pytest.mark.parametrize(
    "key,value",
    [
        ("client_id", ""),
        ("resource", "https://foreign.example/mcp"),
        ("redirect_uri", "https://foreign.example/callback"),
        ("redirect_uri", "javascript:alert(1)"),
        ("redirect_uri", CALLBACK + "#fragment"),
        ("redirect_uri", "https://user:password@client.example/callback"),
        ("scope", "ops-pilot:read unknown:admin"),
        ("scope", "ops-pilot:write"),
        ("code_challenge", "short"),
        ("code_challenge", "/" * 43),
        ("redirect_uri_explicit", "maybe"),
        ("state", "a" * 2049),
    ],
)
def test_invalid_context_never_collects_credentials(flow, key, value):
    response = flow.client.get("/oauth/login", params=PARAMS | {key: value})
    assert response.status_code == 400
    assert 'name="password"' not in response.text
    assert "Start a fresh connection" in response.text
    flow.auth.assert_not_awaited()
    flow.code.assert_not_awaited()


def test_unknown_client_and_unregistered_scope_rejected(flow):
    flow.lookup.return_value = None
    assert flow.client.get("/oauth/login", params=PARAMS).status_code == 400
    flow.lookup.return_value = flow.registered
    flow.registered.scope = "ops-pilot:read"
    assert (
        flow.client.get(
            "/oauth/login", params=PARAMS | {"scope": "ops-pilot:read ops-pilot:write"}
        ).status_code
        == 400
    )


def test_duplicate_context_rejected(flow):
    response = flow.client.get("/oauth/login?" + urlencode(PARAMS) + "&client_id=another")
    assert response.status_code == 400


def test_missing_browser_proof_rejected_before_db_and_auth(flow):
    response = submit(flow, PARAMS)
    assert response.status_code == 403
    flow.lookup.assert_not_awaited()
    flow.auth.assert_not_awaited()
    flow.code.assert_not_awaited()


@pytest.mark.parametrize(
    "key,value",
    [
        ("client_id", "other-client"),
        ("redirect_uri", "https://foreign.example/callback"),
        ("state", "altered"),
        ("scope", "ops-pilot:read ops-pilot:write"),
        ("code_challenge", "b" * 43),
        ("resource", "https://foreign.example/mcp"),
        ("redirect_uri_explicit", "false"),
    ],
)
def test_hidden_authorization_fields_cannot_be_changed(flow, key, value):
    _, fields = open_form(flow)
    flow.lookup.reset_mock()
    response = submit(flow, fields, **{key: value})
    assert response.status_code == 403
    flow.lookup.assert_not_awaited()
    flow.auth.assert_not_awaited()
    flow.code.assert_not_awaited()


def test_proof_cannot_be_reused_in_another_browser(flow):
    _, fields = open_form(flow)
    with TestClient(flow.app, base_url=BASE) as other_browser:
        response = other_browser.post("/oauth/login", data=fields | {"decision": "deny"})
    assert response.status_code == 403
    flow.code.assert_not_awaited()


def test_expired_proof_rejected(flow, monkeypatch):
    monkeypatch.setattr(oauth_form.time, "time", lambda: 1000)
    _, fields = open_form(flow)
    monkeypatch.setattr(oauth_form.time, "time", lambda: 1601)
    assert submit(flow, fields).status_code == 403
    flow.auth.assert_not_awaited()


@pytest.mark.parametrize("proof", ["", "nope", "1000.é", "١٠٠٠." + "a" * 64])
def test_malformed_proof_is_a_safe_error(flow, proof):
    _, fields = open_form(flow)
    assert submit(flow, fields, csrf_token=proof).status_code == 403
    flow.auth.assert_not_awaited()


def test_cross_origin_submission_rejected(flow):
    _, fields = open_form(flow)
    response = flow.client.post(
        "/oauth/login",
        data=fields | {"decision": "deny"},
        headers={"Origin": "https://foreign.example"},
    )
    assert response.status_code == 403
    flow.code.assert_not_awaited()


def test_wrong_password_keeps_context_and_email_but_never_password(flow):
    flow.auth.return_value = None
    _, fields = open_form(flow)
    response = submit(flow, fields, password="never-reflect-this-password")
    assert response.status_code == 401
    assert "Invalid email or password" in response.text
    assert 'value="user@example.com"' in response.text
    assert "never-reflect-this-password" not in response.text
    retry = HiddenFields(response.text).values
    assert all(retry[key] == fields[key] for key in PARAMS)
    flow.auth.return_value = SimpleNamespace(id=uuid4())
    assert submit(flow, retry).status_code == 302


@pytest.mark.parametrize(
    "exception,status,message",
    [
        (AuthRateLimitExceeded(42), 429, "Too many attempts"),
        (AuthRateLimitUnavailable(), 503, "temporarily unavailable"),
    ],
)
def test_rate_limit_failures_are_styled_and_do_not_authenticate(flow, exception, status, message):
    _, fields = open_form(flow)
    flow.rate.side_effect = exception
    response = submit(flow, fields)
    assert response.status_code == status
    assert message in response.text
    assert 'id="authorization-form"' in response.text
    if status == 429:
        assert response.headers["retry-after"] == "42"
    flow.auth.assert_not_awaited()
    flow.code.assert_not_awaited()


def test_success_preserves_oauth_context_and_pkce(flow):
    _, fields = open_form(flow)
    response = submit(flow, fields)
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == CALLBACK
    assert parse_qs(location.query) == {
        "code": ["one-use-authorization-code"],
        "state": [PARAMS["state"]],
        "iss": [BASE],
    }
    flow.rate.assert_awaited_once()
    flow.auth.assert_awaited_once_with(flow.session, "user@example.com", "test-password")
    flow.code.assert_awaited_once_with(
        session=flow.session,
        client_id=PARAMS["client_id"],
        user_id=flow.auth.return_value.id,
        redirect_uri=CALLBACK,
        redirect_uri_provided_explicitly=True,
        scopes=["ops-pilot:read"],
        code_challenge=PARAMS["code_challenge"],
        resource=PARAMS["resource"],
    )
    assert response.headers["cache-control"] == "no-store"


def test_cancel_needs_no_credentials_and_creates_no_code(flow):
    _, fields = open_form(flow)
    response = flow.client.post("/oauth/login", data=fields | {"decision": "deny"})
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "error": ["access_denied"],
        "state": [PARAMS["state"]],
        "iss": [BASE],
    }
    flow.rate.assert_not_awaited()
    flow.auth.assert_not_awaited()
    flow.code.assert_not_awaited()


def test_client_is_revalidated_when_form_is_submitted(flow):
    _, fields = open_form(flow)
    flow.lookup.return_value = None
    assert submit(flow, fields).status_code == 400
    flow.auth.assert_not_awaited()
    flow.code.assert_not_awaited()


def test_multiple_tabs_keep_independent_authorization_contexts(flow):
    _, first = open_form(flow, state="first")
    nonce = flow.client.cookies.get("__Host-opspilot_oauth_browser")
    _, second = open_form(flow, state="second")
    assert flow.client.cookies.get("__Host-opspilot_oauth_browser") == nonce
    assert first["csrf_token"] != second["csrf_token"]
    for fields in (first, second):
        response = submit(flow, fields)
        assert response.status_code == 302
        assert parse_qs(urlsplit(response.headers["location"]).query)["state"] == [fields["state"]]


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "invalid"},
        {"password": ""},
        {"password": "x" * 129},
        {"email": "a" * 321},
    ],
)
def test_invalid_credentials_are_bounded_and_no_code_is_created(flow, changes):
    _, fields = open_form(flow)
    assert submit(flow, fields, **changes).status_code == 422
    flow.auth.assert_not_awaited()
    flow.code.assert_not_awaited()


def test_duplicate_credentials_rejected(flow):
    _, fields = open_form(flow)
    data = urlencode(fields | {"email": "user@example.com", "password": "test-password"})
    response = flow.client.post(
        "/oauth/login",
        content=data + "&password=another",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400
    flow.auth.assert_not_awaited()


def test_uploaded_credentials_are_rejected(flow):
    _, fields = open_form(flow)
    response = flow.client.post(
        "/oauth/login",
        data=fields,
        files={"password": ("password.txt", b"test-password", "text/plain")},
    )
    assert response.status_code == 400
    flow.auth.assert_not_awaited()


def test_form_token_rejects_future_timestamp_and_wrong_secret(monkeypatch):
    monkeypatch.setattr(oauth_form.time, "time", lambda: 2000)
    nonce = oauth_form.browser_nonce(None)
    proof = oauth_form.create_form_token("secret", nonce, PARAMS)
    assert oauth_form.valid_form_token("secret", nonce, PARAMS, proof)
    assert not oauth_form.valid_form_token("wrong", nonce, PARAMS, proof)
    monkeypatch.setattr(oauth_form.time, "time", lambda: 1969)
    assert not oauth_form.valid_form_token("secret", nonce, PARAMS, proof)
