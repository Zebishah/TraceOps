"""Voyage reranking with bounded retries and strict score validation."""

import logging
import math
from functools import lru_cache
from typing import Any, cast

import httpx

from ops_pilot.core.config import get_settings
from ops_pilot.integrations.observability import observe_external_call
from ops_pilot.integrations.retry import request_with_retry

logger = logging.getLogger(__name__)
MAX_RERANK_ATTEMPTS = 4


@lru_cache
def get_voyage_reranker_client() -> httpx.AsyncClient:
    settings = get_settings()

    return httpx.AsyncClient(
        base_url="https://api.voyageai.com",
        headers={
            "Authorization": f"Bearer {settings.voyage_api_key}",
            "Content-Type": "application/json",
        },
        timeout=settings.voyage_timeout_seconds,
    )


async def close_voyage_reranker_client() -> None:
    if get_voyage_reranker_client.cache_info().currsize == 0:
        return

    client = get_voyage_reranker_client()
    await client.aclose()
    get_voyage_reranker_client.cache_clear()


def validate_reranker_response(
    *,
    payload: Any,
    expected_count: int,
) -> list[float]:
    """Require one finite score for every requested passage."""

    if not isinstance(payload, dict):
        raise RuntimeError("Voyage returned an invalid reranker response")

    data = payload.get("data")

    if not isinstance(data, list) or len(data) != expected_count:
        raise RuntimeError("Voyage reranker score count does not match passage count")

    scores = [0.0] * expected_count
    seen: set[int] = set()

    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError("Voyage returned an invalid reranker item")

        index = item.get("index")
        raw_score = item.get("relevance_score")

        if type(index) is not int or index < 0 or index >= expected_count or index in seen:
            raise RuntimeError("Voyage returned duplicate or invalid document index")

        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise RuntimeError("Voyage returned an invalid score")

        score = float(raw_score)

        if not math.isfinite(score):
            raise RuntimeError("Voyage returned a nonfinite score")

        seen.add(index)
        scores[index] = score

    if seen != set(range(expected_count)):
        raise RuntimeError("Voyage reranker indices are incomplete")

    return scores


async def rerank_passages(
    *,
    query: str,
    passages: list[str],
) -> list[float]:
    if not passages:
        return []

    settings = get_settings()
    client = get_voyage_reranker_client()

    async def send_request(attempt: int) -> httpx.Response:
        async def call() -> httpx.Response:
            return await client.post(
                "/v1/rerank",
                json={
                    "model": settings.reranker_model,
                    "query": query,
                    "documents": passages,
                    "return_documents": False,
                },
            )

        return await observe_external_call(
            provider="voyage",
            operation="rerank",
            metadata={
                "model": settings.reranker_model,
                "attempt": attempt + 1,
            },
            call=call,
        )

    response = await request_with_retry(
        send=send_request,
        max_attempts=MAX_RERANK_ATTEMPTS,
    )

    logger.info(
        "external_http_response",
        extra={
            "provider": "voyage",
            "operation": "rerank",
            "model": settings.reranker_model,
            "status_code": response.status_code,
        },
    )

    response.raise_for_status()

    payload = cast(dict[str, Any], response.json())

    return validate_reranker_response(
        payload=payload,
        expected_count=len(passages),
    )
