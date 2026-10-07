from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from ops_pilot.cache.redis import get_redis_client
from ops_pilot.db.session import async_session_factory

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
    }


@router.get("/health/ready")
async def readiness_check() -> dict[str, str]:
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE),
            detail="Database unavailable",
        ) from exc

    try:
        redis = get_redis_client()

        await redis.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE),
            detail="Redis unavailable",
        ) from exc

    return {
        "status": "ready",
        "database": "connected",
        "redis": "connected",
    }
