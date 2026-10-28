"""Bounded retry handling for HTTP integrations."""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

MAX_RETRY_DELAY_SECONDS = 10.0
DEFAULT_RETRY_BUDGET_SECONDS = 30.0


def should_retry_response(response: httpx.Response) -> bool:
    return response.status_code in RETRYABLE_STATUS_CODES


def retry_delay_seconds(
    *,
    response: httpx.Response,
    attempt: int,
    base_delay_seconds: float = 1.0,
) -> float:
    """Parse Retry-After safely and cap all retry delays."""
    if attempt < 0:
        raise ValueError("attempt must be nonnegative")

    if not math.isfinite(base_delay_seconds) or base_delay_seconds < 0:
        raise ValueError("base_delay_seconds must be finite and nonnegative")

    delay = min(
        base_delay_seconds * (2.0 ** min(attempt, 30)),
        MAX_RETRY_DELAY_SECONDS,
    )

    raw = response.headers.get("Retry-After")

    if raw is not None:
        try:
            numeric = float(raw)
        except (ValueError, OverflowError):
            numeric = None

        if numeric is not None and math.isfinite(numeric):
            delay = max(0.0, numeric)
        else:
            try:
                parsed = parsedate_to_datetime(raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                delay = max(
                    0.0,
                    (parsed - datetime.now(UTC)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                pass

    return min(delay, MAX_RETRY_DELAY_SECONDS)


async def request_with_retry(
    *,
    send: Callable[[int], Awaitable[httpx.Response]],
    max_attempts: int,
    budget_seconds: float = DEFAULT_RETRY_BUDGET_SECONDS,
) -> httpx.Response:
    """Retry transport failures and temporary HTTP responses.

    The total budget covers requests and delays. Never retry
    cancellation or arbitrary programming exceptions.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")

    async with asyncio.timeout(budget_seconds):
        for attempt in range(max_attempts):
            try:
                response = await send(attempt)
            except httpx.TransportError:
                if attempt == max_attempts - 1:
                    raise

                logger.warning(
                    "http_transport_retry",
                    extra={"attempt": attempt + 1},
                )

                await asyncio.sleep(
                    min(
                        2.0**attempt,
                        MAX_RETRY_DELAY_SECONDS,
                    )
                )
                continue

            if not should_retry_response(response) or attempt == max_attempts - 1:
                return response

            await asyncio.sleep(
                retry_delay_seconds(
                    response=response,
                    attempt=attempt,
                )
            )

    raise RuntimeError("HTTP retry loop terminated unexpectedly")
