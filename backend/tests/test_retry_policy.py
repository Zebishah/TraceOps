import httpx
import pytest

from ops_pilot.integrations.retry import (
    retry_delay_seconds,
    should_retry_response,
)


@pytest.mark.parametrize(
    "status_code",
    [
        429,
        500,
        502,
        503,
        504,
    ],
)
def test_retryable_status_codes(
    status_code: int,
) -> None:
    response = httpx.Response(
        status_code=status_code,
    )

    assert should_retry_response(response) is True


@pytest.mark.parametrize(
    "status_code",
    [
        400,
        401,
        403,
        404,
        409,
        422,
    ],
)
def test_non_retryable_status_codes(
    status_code: int,
) -> None:
    response = httpx.Response(
        status_code=status_code,
    )

    assert should_retry_response(response) is False


def test_retry_after_header_is_respected() -> None:
    response = httpx.Response(
        status_code=429,
        headers={
            "Retry-After": "3",
        },
    )

    assert (
        retry_delay_seconds(
            response=response,
            attempt=0,
        )
        == 3.0
    )


def test_retry_delay_uses_exponential_backoff() -> None:
    response = httpx.Response(
        status_code=503,
    )

    assert (
        retry_delay_seconds(
            response=response,
            attempt=0,
        )
        == 1.0
    )

    assert (
        retry_delay_seconds(
            response=response,
            attempt=1,
        )
        == 2.0
    )

    assert (
        retry_delay_seconds(
            response=response,
            attempt=2,
        )
        == 4.0
    )
