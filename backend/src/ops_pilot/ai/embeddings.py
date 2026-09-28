from functools import lru_cache
from typing import Any, cast

import httpx

from ops_pilot.core.config import get_settings


@lru_cache
def get_mistral_embedding_client() -> httpx.AsyncClient:
    settings = get_settings()

    return httpx.AsyncClient(
        base_url="https://api.mistral.ai",
        headers={
            "Authorization": f"Bearer {settings.mistral_api_key}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


async def close_mistral_embedding_client() -> None:
    if get_mistral_embedding_client.cache_info().currsize == 0:
        return

    client = get_mistral_embedding_client()

    await client.aclose()

    get_mistral_embedding_client.cache_clear()


async def embed_texts(
    texts: list[str],
) -> list[list[float]]:
    if not texts:
        return []

    settings = get_settings()
    client = get_mistral_embedding_client()

    response = await client.post(
        "/v1/embeddings",
        json={
            "model": settings.embedding_model,
            "input": texts,
        },
    )

    response.raise_for_status()

    payload = cast(dict[str, Any], response.json())

    data = payload.get("data")

    if not isinstance(data, list):
        raise RuntimeError("Mistral returned an invalid embeddings response")

    ordered = sorted(
        data,
        key=lambda item: int(item["index"]),
    )

    embeddings: list[list[float]] = []

    for item in ordered:
        vector = [float(value) for value in item["embedding"]]

        if len(vector) != settings.embedding_dimension:
            raise RuntimeError("Mistral embedding dimension does not match configuration")

        embeddings.append(vector)

    if len(embeddings) != len(texts):
        raise RuntimeError("Mistral embedding count does not match input count")

    return embeddings


async def embed_query(
    query: str,
) -> list[float]:
    embeddings = await embed_texts([query])

    return embeddings[0]
