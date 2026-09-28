from functools import lru_cache
from typing import Any, cast

import httpx

from ops_pilot.core.config import get_settings


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


async def rerank_passages(
    *,
    query: str,
    passages: list[str],
) -> list[float]:
    if not passages:
        return []

    settings = get_settings()
    client = get_voyage_reranker_client()

    response = await client.post(
        "/v1/rerank",
        json={
            "model": settings.reranker_model,
            "query": query,
            "documents": passages,
            "return_documents": False,
        },
    )

    response.raise_for_status()

    payload = cast(dict[str, Any], response.json())

    data = payload.get("data")

    if not isinstance(data, list):
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
