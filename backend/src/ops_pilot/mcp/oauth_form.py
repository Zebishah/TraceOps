"""Short-lived browser proof bound to the exact OAuth authorization request."""

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Mapping

AUTHORIZATION_FIELDS = (
    "client_id",
    "redirect_uri",
    "state",
    "scope",
    "code_challenge",
    "resource",
    "redirect_uri_explicit",
)
FORM_LIFETIME_SECONDS = 600
_BROWSER_NONCE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def browser_nonce(value: str | None) -> str:
    return (
        value
        if value is not None and _BROWSER_NONCE.fullmatch(value)
        else secrets.token_urlsafe(32)
    )


def _signature(secret: str, nonce: str, values: Mapping[str, str], issued: str) -> str:
    payload = json.dumps(
        [
            "opspilot-oauth-consent-v1",
            nonce,
            issued,
            *[values.get(key, "") for key in AUTHORIZATION_FIELDS],
        ],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_form_token(secret: str, nonce: str, values: Mapping[str, str]) -> str:
    issued = str(int(time.time()))
    return f"{issued}.{_signature(secret, nonce, values, issued)}"


def valid_form_token(
    secret: str,
    nonce: str | None,
    values: Mapping[str, str],
    token: str,
) -> bool:
    if nonce is None or _BROWSER_NONCE.fullmatch(nonce) is None:
        return False
    issued, separator, signature = token.partition(".")
    if re.fullmatch(r"[0-9a-f]{64}", signature) is None:
        return False
    if not separator or not issued.isascii() or not issued.isdecimal() or len(issued) > 12:
        return False
    age = int(time.time()) - int(issued)
    if age < -30 or age > FORM_LIFETIME_SECONDS:
        return False
    return hmac.compare_digest(_signature(secret, nonce, values, issued), signature)
