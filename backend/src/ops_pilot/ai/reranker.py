import asyncio
import logging
from functools import lru_cache
from typing import Any, cast

import httpx

from ops_pilot.core.config import get_settings
from ops_pilot.integrations.observability import (
    observe_external_call,
)
from ops_pilot.integrations.retry import (
    retry_delay_seconds,
    should_retry_response,
)

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


async def rerank_passages(
    *,
    query: str,
    passages: list[str],
) -> list[float]:
    if not passages:
        return []

    settings = get_settings()
    client = get_voyage_reranker_client()

    response: httpx.Response | None = None

    for attempt in range(MAX_RERANK_ATTEMPTS):

        async def send_request() -> httpx.Response:
            return await client.post(
                "/v1/rerank",
                json={
                    "model": settings.reranker_model,
                    "query": query,
                    "documents": passages,
                    "return_documents": False,
                },
            )

        response = await observe_external_call(
            provider="voyage",
            operation="rerank",
            metadata={
                "model": settings.reranker_model,
                "attempt": attempt + 1,
            },
            call=send_request,
        )
        logger.info(
            "external_http_response",
            extra={
                "provider": "voyage",
                "operation": "rerank",
                "model": settings.reranker_model,
                "attempt": attempt + 1,
                "status_code": response.status_code,
            },
        )
        if not should_retry_response(response):
            break

        if attempt == MAX_RERANK_ATTEMPTS - 1:
            break

        await asyncio.sleep(
            retry_delay_seconds(
                response=response,
                attempt=attempt,
            )
        )

    if response is None:
        raise RuntimeError("Voyage reranker did not return a response")

    response.raise_for_status()

    payload = cast(
        dict[str, Any],
        response.json(),
    )

    data = payload.get("data")

    if not isinstance(
        data,
        list,
    ):
        raise RuntimeError("Voyage returned an invalid reranker response")

    scores = [0.0] * len(passages)

    for item in data:
        index = int(item["index"])

        score = float(item["relevance_score"])

        if index < 0 or index >= len(passages):
            raise RuntimeError("Voyage returned an invalid document index")

        scores[index] = score

    if len(data) != len(passages):
        raise RuntimeError("Voyage reranker score count does not match passage count")

    return scores
