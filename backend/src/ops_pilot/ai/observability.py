import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import TypeVar

from ops_pilot.core.config import get_settings

T = TypeVar("T")

logger = logging.getLogger(__name__)


async def observe_llm_call[T](
    *,
    operation: str,
    call: Callable[[], Awaitable[T]],
) -> T:
    settings = get_settings()

    metadata = {
        "provider": "groq",
        "model": settings.generation_model,
        "operation": operation,
    }

    logger.info(
        "llm_call_started",
        extra=metadata,
    )

    started_at = perf_counter()

    try:
        result = await call()
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000

        logger.exception(
            "llm_call_failed",
            extra={
                **metadata,
                "duration_ms": round(
                    duration_ms,
                    2,
                ),
            },
        )

        raise

    duration_ms = (perf_counter() - started_at) * 1000

    logger.info(
        "llm_call_succeeded",
        extra={
            **metadata,
            "duration_ms": round(
                duration_ms,
                2,
            ),
        },
    )

    return result
