import httpx

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}


def should_retry_response(
    response: httpx.Response,
) -> bool:
    return response.status_code in RETRYABLE_STATUS_CODES


def retry_delay_seconds(
    *,
    response: httpx.Response,
    attempt: int,
    base_delay_seconds: float = 1.0,
) -> float:
    retry_after = response.headers.get(
        "Retry-After",
    )

    if retry_after is not None:
        try:
            return max(
                float(retry_after),
                0.0,
            )
        except ValueError:
            pass

    return base_delay_seconds * float(2**attempt)
