import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)


async def observe_external_call[T](
    *,
    provider: str,
    operation: str,
    call: Callable[[], Awaitable[T]],
    metadata: dict[str, Any] | None = None,
) -> T:
    base_metadata: dict[str, Any] = {
        "provider": provider,
        "operation": operation,
    }

    if metadata is not None:
        base_metadata.update(metadata)

    logger.info(
        "external_call_started",
        extra=base_metadata,
    )

    started_at = perf_counter()

    try:
        result = await call()
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000

        logger.exception(
            "external_call_failed",
            extra={
                **base_metadata,
                "duration_ms": round(
                    duration_ms,
                    2,
                ),
            },
        )
        raise

    duration_ms = (perf_counter() - started_at) * 1000

    logger.info(
        "external_call_succeeded",
        extra={
            **base_metadata,
            "duration_ms": round(
                duration_ms,
                2,
            ),
        },
    )

    return result
