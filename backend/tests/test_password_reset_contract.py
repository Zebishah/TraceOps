"""Contract tests for recovery token secrecy and web session invalidation."""

import hashlib
import re
import secrets

from ops_pilot.core.security import create_access_token, decode_access_token
from ops_pilot.services.password_recovery import _TOKEN_PATTERN


def test_password_reset_token_format_and_storage_hash() -> None:
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    assert re.fullmatch(_TOKEN_PATTERN, raw)
    assert len(digest) == 64
    assert raw != digest


def test_access_token_carries_authentication_version() -> None:
    old = decode_access_token(create_access_token(subject="user", auth_version=0))
    rotated = decode_access_token(create_access_token(subject="user", auth_version=1))
    assert old["auth_ver"] == 0
    assert rotated["auth_ver"] == 1
    assert old["auth_ver"] != rotated["auth_ver"]
