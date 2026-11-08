"""Short-lived dashboard snapshots, authorized before lookup and versioned after writes."""

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import cast, get_type_hints

from fastapi.encoders import jsonable_encoder
from starlette.requests import Request

from ops_pilot.models.membership import Membership
from pydantic import TypeAdapter, ValidationError

from ops_pilot.cache.redis import get_redis_client
from ops_pilot.core.config import get_settings

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 30
VERSION_TTL_SECONDS = 86400
REDIS_TIMEOUT_SECONDS = 0.2
_VERSIONS = """
local values = {}
for i = 1, 2 do
    local value = redis.call('GET', KEYS[i])
    if not value then
        value = ARGV[i]
        redis.call('SET', KEYS[i], value, 'EX', ARGV[3])
    end
    values[i] = value
end
return values
"""


def version_key(scope: str) -> str:
    return f"{get_settings().redis_key_prefix}:v2:dashboard:version:{scope}"


async def invalidate_dashboard_cache(scopes: set[str]) -> None:
    """Rotate namespaces, never scan/delete all tenants' response keys."""
    if not scopes:
        return
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            async with get_redis_client().pipeline(transaction=True) as pipe:
                for scope in scopes:
                    pipe.set(version_key(scope), uuid.uuid4().hex, ex=VERSION_TTL_SECONDS)
                await pipe.execute()
    except Exception:
        # A committed business operation must never fail because Redis is unavailable.
        logger.warning("Dashboard cache invalidation unavailable; snapshots expire shortly")


def dashboard_cached[**P, T](function: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """FastAPI resolves CurrentMembership before invoking this wrapper, even on hits."""
    adapter = TypeAdapter(get_type_hints(function)["return"])

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        membership = cast(Membership, kwargs["membership"])
        organization_id = str(kwargs["organization_id"])
        request = cast(Request, kwargs["request"])
        parameters = {
            key: value
            for key, value in kwargs.items()
            if key not in {"session", "membership", "request"}
        }
        # Include the member and role as well as all filters, pagination, and identifiers.
        identity = json.dumps(
            [function.__name__, str(membership.user_id), str(membership.role), parameters],
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(identity.encode()).hexdigest()
        key: str | None = None
        try:
            async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
                redis = get_redis_client()
                versions = await redis.eval(
                    _VERSIONS,
                    2,
                    version_key("*"),
                    version_key(organization_id),
                    uuid.uuid4().hex,
                    uuid.uuid4().hex,
                    VERSION_TTL_SECONDS,
                )
                # Random versions prevent an expired/evicted version key reviving old snapshots.
                key = (
                    f"{get_settings().redis_key_prefix}:v2:dashboard:{versions[0]}:"
                    f"{organization_id}:{versions[1]}:{digest}"
                )
                if request.headers.get("x-opspilot-refresh") != "1":
                    cached = await redis.get(key)
                    if cached is not None:
                        try:
                            return cast(T, adapter.validate_json(cached))
                        except (ValidationError, ValueError, TypeError):
                            await redis.delete(key)
        except Exception:
            key = None
        result = await function(*args, **kwargs)
        if key is not None:
            try:
                async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
                    await get_redis_client().set(
                        key,
                        json.dumps(jsonable_encoder(result), separators=(",", ":")),
                        ex=CACHE_TTL_SECONDS,
                    )
            except Exception:
                pass
        # A concurrent commit changes the namespace; an older reader can only fill its old key.
        return result

    return wrapped
