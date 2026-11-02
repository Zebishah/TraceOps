from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_pilot.core.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
    pool_use_lifo=True,
    connect_args={
        "connect_timeout": settings.database_connect_timeout_seconds,
    },
)
