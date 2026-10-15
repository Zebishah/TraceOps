import logging
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


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
    }


async def check_database() -> tuple[bool, float]:
    started_at = perf_counter()

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000

        logger.exception(
            "readiness_dependency_failed",
            extra={
                "provider": "postgresql",
                "operation": "health_check",
                "duration_ms": round(
                    duration_ms,
                    2,
                ),
            },
        )

        return False, duration_ms

    duration_ms = (perf_counter() - started_at) * 1000

    return True, duration_ms


async def check_redis() -> tuple[bool, float]:
    started_at = perf_counter()

    try:
        redis = get_redis_client()

        await redis.ping()
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000

        logger.exception(
            "readiness_dependency_failed",
            extra={
                "provider": "redis",
                "operation": "health_check",
                "duration_ms": round(
                    duration_ms,
                    2,
                ),
            },
        )

        return False, duration_ms

    duration_ms = (perf_counter() - started_at) * 1000

    return True, duration_ms


async def check_qdrant() -> tuple[bool, float]:
    started_at = perf_counter()

    try:
        settings = get_settings()

        client = get_qdrant_client()

        await client.collection_exists(
            collection_name=(settings.qdrant_collection_name),
        )
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000

        logger.exception(
            "readiness_dependency_failed",
            extra={
                "provider": "qdrant",
                "operation": "health_check",
                "duration_ms": round(
                    duration_ms,
                    2,
                ),
            },
        )

        return False, duration_ms

    duration_ms = (perf_counter() - started_at) * 1000

    return True, duration_ms


@router.get("/health/ready")
async def readiness_check() -> JSONResponse:
    database_ok, database_duration = await check_database()

    redis_ok, redis_duration = await check_redis()

    qdrant_ok, qdrant_duration = await check_qdrant()

    dependencies = {
        "database": {
            "status": ("connected" if database_ok else "unavailable"),
            "duration_ms": round(
                database_duration,
                2,
            ),
        },
        "redis": {
            "status": ("connected" if redis_ok else "unavailable"),
            "duration_ms": round(
                redis_duration,
                2,
            ),
        },
        "qdrant": {
            "status": ("connected" if qdrant_ok else "unavailable"),
            "duration_ms": round(
                qdrant_duration,
                2,
            ),
        },
    }

    ready = database_ok and redis_ok and qdrant_ok

    return JSONResponse(
        status_code=(200 if ready else 503),
        content={
            "status": ("ready" if ready else "not_ready"),
            "dependencies": dependencies,
        },
    )
