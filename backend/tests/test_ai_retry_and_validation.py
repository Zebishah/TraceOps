"""A01-A04: AI retry bounds and provider response integrity."""

import asyncio
import math
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from ops_pilot.ai import embeddings, reranker
from ops_pilot.integrations.retry import (
    request_with_retry,
    retry_delay_seconds,
)


@pytest.mark.parametrize(
    "header",
    ["999999999", "inf", "NaN", "invalid", "-20"],
)
def test_retry_after_never_causes_unbounded_sleep(
    header: str,
) -> None:
    response = httpx.Response(
        429,
        headers={"Retry-After": header},
    )

    delay = retry_delay_seconds(
        response=response,
        attempt=0,
    )

    assert math.isfinite(delay)
    assert 0 <= delay <= 10


def test_retry_after_supports_http_date() -> None:
    future = datetime.now(UTC) + timedelta(hours=2)

    response = httpx.Response(
        429,
        headers={
            "Retry-After": format_datetime(future, usegmt=True),
        },
    )

    assert (
        retry_delay_seconds(
            response=response,
            attempt=0,
        )
        == 10
    )


@pytest.mark.anyio
async def test_temporary_transport_failure_is_retried() -> None:
    send = AsyncMock(
        side_effect=[
            httpx.ConnectError("temporary failure"),
            httpx.Response(200),
        ],
    )

    response = await request_with_retry(
        send=send,
        max_attempts=3,
    )

    assert response.status_code == 200
    assert send.await_count == 2


@pytest.mark.anyio
async def test_retry_stops_at_maximum_attempts() -> None:
    send = AsyncMock(
        side_effect=httpx.ConnectError("still unavailable"),
    )

    with pytest.raises(httpx.ConnectError):
        await request_with_retry(
            send=send,
            max_attempts=2,
        )

    assert send.await_count == 2


@pytest.mark.anyio
async def test_retry_respects_total_budget() -> None:
    async def slow_request(attempt: int) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200)

    with pytest.raises(TimeoutError):
        await request_with_retry(
            send=slow_request,
            max_attempts=3,
            budget_seconds=0.01,
        )


@pytest.mark.parametrize(
    "indices",
    [
        [0, 0],
        [0, 2],
        [-1, 1],
        [True, 1],
    ],
)
def test_embeddings_reject_bad_indices(indices: list) -> None:
    payload = {"data": [{"index": index, "embedding": [0.1, 0.2]} for index in indices]}

    with pytest.raises(RuntimeError):
        embeddings.validate_embedding_response(
            payload=payload,
            expected_count=2,
            expected_dimension=2,
        )


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf")])
def test_embeddings_reject_nonfinite_values(bad_value: float) -> None:
    with pytest.raises(RuntimeError):
        embeddings.validate_embedding_response(
            payload={
                "data": [
                    {"index": 0, "embedding": [0.1, bad_value]},
                ]
            },
            expected_count=1,
            expected_dimension=2,
        )


@pytest.mark.parametrize(
    "indices",
    [
        [0, 0],
        [0, 2],
        [-1, 1],
        [True, 1],
    ],
)
def test_reranker_rejects_bad_indices(indices: list) -> None:
    payload = {"data": [{"index": index, "relevance_score": 0.8} for index in indices]}

    with pytest.raises(RuntimeError):
        reranker.validate_reranker_response(
            payload=payload,
            expected_count=2,
        )


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf")])
def test_reranker_rejects_nonfinite_scores(bad_score: float) -> None:
    with pytest.raises(RuntimeError):
        reranker.validate_reranker_response(
            payload={
                "data": [
                    {"index": 0, "relevance_score": bad_score},
                ]
            },
            expected_count=1,
        )


@pytest.mark.anyio
async def test_embedding_client_retries_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        post=AsyncMock(
            side_effect=[
                httpx.ReadTimeout("temporary timeout"),
                httpx.Response(
                    200,
                    request=httpx.Request(
                        "POST",
                        "https://api.mistral.ai/v1/embeddings",
                    ),
                    json={
                        "data": [
                            {"index": 0, "embedding": [0.1, 0.2]},
                        ]
                    },
                ),
            ]
        )
    )

    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_model="mistral-embed",
            embedding_dimension=2,
        ),
    )
    monkeypatch.setattr(
        embeddings,
        "get_mistral_embedding_client",
        lambda: client,
    )

    assert await embeddings.embed_texts(["example"]) == [[0.1, 0.2]]
    assert client.post.await_count == 2


@pytest.mark.anyio
async def test_reranker_client_retries_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        post=AsyncMock(
            side_effect=[
                httpx.ConnectError("temporary connection failure"),
                httpx.Response(
                    200,
                    request=httpx.Request(
                        "POST",
                        "https://api.voyageai.com/v1/rerank",
                    ),
                    json={
                        "data": [
                            {"index": 0, "relevance_score": 0.9},
                        ]
                    },
                ),
            ]
        )
    )

    monkeypatch.setattr(
        reranker,
        "get_settings",
        lambda: SimpleNamespace(
            reranker_model="rerank-3-lite",
        ),
    )
    monkeypatch.setattr(
        reranker,
        "get_voyage_reranker_client",
        lambda: client,
    )

    assert await reranker.rerank_passages(
        query="example",
        passages=["passage"],
    ) == [0.9]

    assert client.post.await_count == 2
