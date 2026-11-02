import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)


async def observe_workflow_step[T](
    *,
    node: str,
    incident_id: object,
    workflow_thread_id: object | None,
    call: Callable[[], Awaitable[T]],
    job_id: object | None = None,
    dispatch_id: object | None = None,
) -> T:
    metadata: dict[str, Any] = {
        "node": node,
        "incident_id": str(incident_id),
    }

    if workflow_thread_id is not None:
        metadata["workflow_thread_id"] = str(workflow_thread_id)
    if job_id is not None:
        metadata["job_id"] = str(job_id)

    if dispatch_id is not None:
        metadata["dispatch_id"] = str(dispatch_id)
    logger.info(
        "workflow_step_started",
        extra=metadata,
    )

    started_at = perf_counter()

    try:
        result = await call()
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000

        logger.exception(
            "workflow_step_failed",
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
        "workflow_step_succeeded",
        extra={
            **metadata,
            "duration_ms": round(
                duration_ms,
                2,
            ),
        },
    )

    return result
