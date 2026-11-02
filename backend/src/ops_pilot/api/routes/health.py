import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ops_pilot.cache.redis import get_redis_client
from ops_pilot.core.config import get_settings
from ops_pilot.db.session import async_session_factory
from ops_pilot.vectorstore.qdrant import get_qdrant_client

router = APIRouter()
logger = logging.getLogger(__name__)

type HealthResult = tuple[bool, float]


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Cheap process health check with no external service calls."""
    return {"status": "ok"}


async def _check_dependency(
    *,
    provider: str,
    operation: Callable[[], Awaitable[bool]],
) -> HealthResult:
    started_at = perf_counter()

    try:
        async with asyncio.timeout(get_settings().health_dependency_timeout_seconds):
            healthy = await operation()

        if not healthy:
            logger.warning(
                "readiness_dependency_unavailable",
                extra={
                    "provider": provider,
                    "operation": "health_check",
                },
            )

    except Exception:
        healthy = False

        logger.exception(
            "readiness_dependency_failed",
            extra={
                "provider": provider,
                "operation": "health_check",
            },
        )

    duration_ms = (perf_counter() - started_at) * 1000
    return healthy, duration_ms


async def _database_available() -> bool:
    async with async_session_factory() as session:
        await session.execute(text("SELECT 1"))

    return True


async def _redis_available() -> bool:
    return bool(await get_redis_client().ping())


async def _qdrant_available() -> bool:
    settings = get_settings()

    return await get_qdrant_client().collection_exists(
        collection_name=settings.qdrant_collection_name,
    )


async def check_database() -> HealthResult:
    return await _check_dependency(
        provider="postgresql",
        operation=_database_available,
    )


async def check_redis() -> HealthResult:
    return await _check_dependency(
        provider="redis",
        operation=_redis_available,
    )


async def check_qdrant() -> HealthResult:
    return await _check_dependency(
        provider="qdrant",
        operation=_qdrant_available,
    )


@router.get("/health/ready")
async def readiness_check() -> JSONResponse:
    database, redis, qdrant = await asyncio.gather(
        check_database(),
        check_redis(),
        check_qdrant(),
    )

    results = {
        "database": database,
        "redis": redis,
        "qdrant": qdrant,
    }

    ready = all(healthy for healthy, _duration in results.values())

    dependencies = {
        name: {
            "status": "connected" if healthy else "unavailable",
            "duration_ms": round(duration_ms, 2),
        }
        for name, (healthy, duration_ms) in results.items()
    }

    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "dependencies": dependencies,
        },
    )
