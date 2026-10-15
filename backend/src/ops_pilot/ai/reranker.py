import asyncio
from functools import lru_cache
from typing import Any, cast

import httpx

from ops_pilot.core.config import get_settings

MAX_RERANK_ATTEMPTS = 4
BASE_RETRY_DELAY_SECONDS = 1.0


@lru_cache
def get_voyage_reranker_client() -> httpx.AsyncClient:
    settings = get_settings()

    return httpx.AsyncClient(
        base_url="https://api.voyageai.com",
        headers={
            "Authorization": f"Bearer {settings.voyage_api_key}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


async def close_voyage_reranker_client() -> None:
    if get_voyage_reranker_client.cache_info().currsize == 0:
        return

    client = get_voyage_reranker_client()

    await client.aclose()

    get_voyage_reranker_client.cache_clear()


def _retry_delay_seconds(
    *,
    response: httpx.Response,
    attempt: int,
) -> float:
    retry_after = response.headers.get(
        "Retry-After",
    )

    if retry_after is not None:
        try:
            retry_after_seconds = float(
                retry_after,
            )

            return max(
                retry_after_seconds,
                0.0,
            )
        except ValueError:
            pass

    delay: float = BASE_RETRY_DELAY_SECONDS * float(2**attempt)

    return delay


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
        response = await client.post(
            "/v1/rerank",
            json={
                "model": settings.reranker_model,
                "query": query,
                "documents": passages,
                "return_documents": False,
            },
        )

        if response.status_code != 429:
            break

        if attempt == MAX_RERANK_ATTEMPTS - 1:
            break

        await asyncio.sleep(
            _retry_delay_seconds(
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
