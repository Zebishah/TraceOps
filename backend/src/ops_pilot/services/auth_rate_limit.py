"""Redis-backed authentication attempt rate limiting."""

import hashlib
import hmac
import ipaddress
from dataclasses import dataclass

from starlette.requests import Request

from ops_pilot.cache.redis import get_redis_client
from ops_pilot.core.config import get_settings

_INCREMENT_SCRIPT = """
local count = redis.call("INCR", KEYS[1])
if count == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
return {count, ttl}
"""


@dataclass(frozen=True)
class AuthRateLimitExceeded(Exception):
    retry_after_seconds: int


class AuthRateLimitUnavailable(Exception):
    pass


def _client_ip(request: Request) -> str:
    """Use the connection peer, not an untrusted forwarded header."""
    if request.client is None:
        return "unknown"

    host = request.client.host

    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        # Test clients and non-IP peers receive a common bucket.
        return "unknown"


def _private_key(value: str) -> str:
    """Avoid putting emails or IP addresses directly in Redis keys."""
    secret = get_settings().jwt_secret_key.encode("utf-8")

    return hmac.new(
        secret,
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def _enforce_limit(
    *,
    category: str,
    identifier: str,
    attempts: int,
    window_seconds: int,
) -> None:
    if attempts <= 0 or window_seconds <= 0:
        raise ValueError("Invalid authentication rate limit")

    settings = get_settings()

    key = f"{settings.redis_key_prefix}:auth-rate:{category}:{_private_key(identifier)}"

    try:
        redis = get_redis_client()

        result = await redis.eval(
            _INCREMENT_SCRIPT,
            1,
            key,
            window_seconds,
        )

        count = int(result[0])
        ttl = max(int(result[1]), 1)

    except Exception as exc:
        raise AuthRateLimitUnavailable("Authentication rate-limit service unavailable") from exc

    if count > attempts:
        raise AuthRateLimitExceeded(
            retry_after_seconds=ttl,
        )


async def enforce_login_rate_limit(
    *,
    request: Request,
    email: str,
) -> None:
    """Apply both IP-level and account-level login attempt limits."""
    ip = _client_ip(request)

    await _enforce_limit(
        category="login-ip",
        identifier=ip,
        attempts=10,
        window_seconds=60,
    )

    await _enforce_limit(
        category="login-account",
        identifier=email.strip().casefold(),
        attempts=5,
        window_seconds=300,
    )


async def enforce_registration_rate_limit(
    *,
    request: Request,
) -> None:
    """Limit new account and organization registrations."""
    await _enforce_limit(
        category="register-ip",
        identifier=_client_ip(request),
        attempts=5,
        window_seconds=3600,
    )


async def enforce_verification_request_limit(*, request: Request, email: str) -> None:
    await _enforce_limit(
        category="verification-ip",
        identifier=_client_ip(request),
        attempts=10,
        window_seconds=3600,
    )
    await _enforce_limit(
        category="verification-email",
        identifier=email.strip().casefold(),
        attempts=3,
        window_seconds=3600,
    )


async def enforce_verification_claim_limit(*, request: Request, email: str | None = None) -> None:
    await _enforce_limit(
        category="verification-claim-ip",
        identifier=_client_ip(request),
        attempts=20,
        window_seconds=60,
    )
    if email is not None:
        await _enforce_limit(
            category="verification-code-account",
            identifier=email.strip().casefold(),
            attempts=5,
            window_seconds=600,
        )


async def enforce_verification_delivery_limit() -> None:
    await _enforce_limit(
        category="verification-daily",
        identifier="application",
        attempts=get_settings().email_verification_daily_limit,
        window_seconds=86400,
    )
