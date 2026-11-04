"""Browser sign-in and consent for existing MCP OAuth clients."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from mcp.server.auth.provider import construct_redirect_uri
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData, QueryParams
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from ops_pilot.core.config import get_settings
from ops_pilot.core.mcp_scopes import validate_mcp_scope_grant
from ops_pilot.db.session import async_session_factory
from ops_pilot.mcp.oauth_form import (
    AUTHORIZATION_FIELDS,
    FORM_LIFETIME_SECONDS,
    browser_nonce,
    create_form_token,
    valid_form_token,
)
from ops_pilot.mcp.oauth_login_ui import render_login
from ops_pilot.schemas.auth import LoginRequest
from ops_pilot.services.auth import authenticate_user
from ops_pilot.services.auth_rate_limit import (
    AuthRateLimitExceeded,
    AuthRateLimitUnavailable,
    enforce_login_rate_limit,
)
from ops_pilot.services.email_verification import requires_email_verification, verification_page_url
from ops_pilot.services.oauth import (
    create_authorization_code,
    get_oauth_client,
    oauth_client_redirect_uris,
)

_LIMITS = {
    "client_id": 512,
    "redirect_uri": 2048,
    "state": 2048,
    "scope": 256,
    "code_challenge": 43,
    "resource": 2048,
    "redirect_uri_explicit": 5,
}
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True)
class AuthorizationContext:
    values: dict[str, str]
    client_name: str
    scopes: list[str]


def _values(data: QueryParams | FormData) -> dict[str, str] | None:
    result: dict[str, str] = {}
    for key in AUTHORIZATION_FIELDS:
        if len(data.getlist(key)) > 1:
            return None
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > _LIMITS[key]:
            return None
        if key != "state" and not value:
            return None
        result[key] = value
    result["redirect_uri_explicit"] = result["redirect_uri_explicit"].lower()
    if result["redirect_uri_explicit"] not in {"true", "false"}:
        return None
    if _CHALLENGE.fullmatch(result["code_challenge"]) is None:
        return None
    uri = result["redirect_uri"]
    if any(ord(char) < 33 or char in "<>\"'" for char in uri):
        return None
    try:
        redirect = urlsplit(uri)
    except ValueError:
        return None
    if (
        not redirect.scheme
        or redirect.fragment
        or redirect.username
        or redirect.password
        or redirect.scheme.lower() in {"javascript", "data", "file", "vbscript", "blob"}
        or (redirect.scheme in {"https", "http"} and not redirect.hostname)
    ):
        return None
    return result


async def _context(session: AsyncSession, values: dict[str, str]) -> AuthorizationContext | None:
    if values["resource"] != str(get_settings().mcp_resource_url):
        return None
    client = await get_oauth_client(session=session, client_id=values["client_id"])
    if client is None or values["redirect_uri"] not in oauth_client_redirect_uris(client):
        return None
    try:
        scopes = validate_mcp_scope_grant(requested=values["scope"], registered=client.scope)
    except ValueError:
        return None
    return AuthorizationContext(values, client.client_name or "Unnamed application", scopes)


def _secure_cookie() -> bool:
    settings = get_settings()
    return settings.environment == "production" or str(
        settings.mcp_authorization_server_url
    ).startswith("https:")


def _cookie_name() -> str:
    return "__Host-opspilot_oauth_browser" if _secure_cookie() else "opspilot_oauth_browser"


def _form_response(
    context: AuthorizationContext,
    nonce: str,
    *,
    error: str = "",
    email: str = "",
    status_code: int = 200,
    retry_after: int | None = None,
    verification_url: str = "",
) -> HTMLResponse:
    response = render_login(
        values=context.values,
        client_name=context.client_name,
        scopes=context.scopes,
        csrf_token=create_form_token(get_settings().jwt_secret_key, nonce, context.values),
        email=email,
        error=error,
        status_code=status_code,
        retry_after=retry_after,
        verification_url=verification_url,
    )
    response.set_cookie(
        _cookie_name(),
        nonce,
        max_age=FORM_LIFETIME_SECONDS,
        path="/",
        secure=_secure_cookie(),
        httponly=True,
        samesite="lax",
    )
    return response


def _invalid_request(*, expired: bool = False) -> HTMLResponse:
    return render_login(
        error=(
            "This connection expired or changed. Return to your AI app and start again."
            if expired
            else "This connection request is not valid. Return to your AI app and start again."
        ),
        status_code=403 if expired else 400,
    )


async def oauth_login_page(request: Request) -> Response:
    values = _values(request.query_params)
    if values is None:
        return _invalid_request()
    async with async_session_factory() as session:
        context = await _context(session, values)
    if context is None:
        return _invalid_request()
    return _form_response(context, browser_nonce(request.cookies.get(_cookie_name())))


async def oauth_login_submit(request: Request) -> Response:
    try:
        form = await request.form(max_files=0, max_fields=16, max_part_size=8192)
    except HTTPException:
        return _invalid_request()
    values = _values(form)
    if values is None or any(
        len(form.getlist(key)) > 1 for key in ("csrf_token", "decision", "email", "password")
    ):
        return _invalid_request()
    proof = form.get("csrf_token", "")
    settings = get_settings()
    if not isinstance(proof, str) or not valid_form_token(
        settings.jwt_secret_key,
        request.cookies.get(_cookie_name()),
        values,
        proof,
    ):
        return _invalid_request(expired=True)
    # Public issuer comes from server configuration; reverse proxies may use an internal URL.
    origin = request.headers.get("origin")
    issuer = urlsplit(str(settings.mcp_authorization_server_url))
    if origin is not None and origin != f"{issuer.scheme}://{issuer.netloc}":
        return _invalid_request(expired=True)
    decision = form.get("decision", "allow")
    if not isinstance(decision, str) or decision not in {"allow", "deny"}:
        return _invalid_request()
    async with async_session_factory() as session:
        context = await _context(session, values)
        if context is None:
            return _invalid_request()
        if decision == "deny":
            location = construct_redirect_uri(
                values["redirect_uri"],
                error="access_denied",
                state=values["state"] or None,
                iss=str(settings.mcp_authorization_server_url),
            )
        else:
            email = form.get("email", "")
            password = form.get("password", "")
            if (
                not isinstance(email, str)
                or not isinstance(password, str)
                or not 1 <= len(password) <= 128
                or len(email) > 320
            ):
                return _form_response(
                    context,
                    str(request.cookies.get(_cookie_name())),
                    error="Enter your email address and password.",
                    status_code=422,
                )
            try:
                credentials = LoginRequest(email=email.strip(), password=password)
            except ValidationError:
                return _form_response(
                    context,
                    str(request.cookies.get(_cookie_name())),
                    error="Enter a valid email address and password.",
                    email=email,
                    status_code=422,
                )
            try:
                await enforce_login_rate_limit(request=request, email=credentials.email)
            except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
                limited = isinstance(exc, AuthRateLimitExceeded)
                return _form_response(
                    context,
                    str(request.cookies.get(_cookie_name())),
                    email=credentials.email,
                    error="Too many attempts. Please try again later."
                    if limited
                    else "Sign-in is temporarily unavailable. Please try again shortly.",
                    status_code=429 if limited else 503,
                    retry_after=exc.retry_after_seconds
                    if isinstance(exc, AuthRateLimitExceeded)
                    else None,
                )
            user = await authenticate_user(session, credentials.email, credentials.password)
            if user is None:
                return _form_response(
                    context,
                    str(request.cookies.get(_cookie_name())),
                    email=credentials.email,
                    error="Invalid email or password.",
                    status_code=401,
                )
            if requires_email_verification(user):
                return _form_response(
                    context,
                    str(request.cookies.get(_cookie_name())),
                    email=credentials.email,
                    error="Verify your email before connecting. Open email verification, "
                    "then return here to sign in again.",
                    status_code=403,
                    verification_url=verification_page_url(),
                )
            code = await create_authorization_code(
                session=session,
                client_id=values["client_id"],
                user_id=user.id,
                redirect_uri=values["redirect_uri"],
                redirect_uri_provided_explicitly=values["redirect_uri_explicit"] == "true",
                scopes=context.scopes,
                code_challenge=values["code_challenge"],
                resource=values["resource"],
            )
            location = construct_redirect_uri(
                values["redirect_uri"],
                code=code,
                state=values["state"] or None,
                iss=str(settings.mcp_authorization_server_url),
            )
    return RedirectResponse(
        location,
        status_code=302,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
