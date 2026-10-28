"""Mistral embeddings with bounded retries and strict validation."""

import asyncio
import logging
import math
from functools import lru_cache
from typing import Any, cast

import httpx

from ops_pilot.core.config import get_settings
from ops_pilot.integrations.observability import observe_external_call
from ops_pilot.integrations.retry import request_with_retry

logger = logging.getLogger(__name__)

MAX_CONCURRENT_EMBEDDING_REQUESTS = 3
MAX_EMBEDDING_ATTEMPTS = 3

_embedding_semaphore: asyncio.Semaphore | None = None


def get_embedding_semaphore() -> asyncio.Semaphore:
    global _embedding_semaphore

    if _embedding_semaphore is None:
        _embedding_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EMBEDDING_REQUESTS)

    return _embedding_semaphore


@lru_cache
def get_mistral_embedding_client() -> httpx.AsyncClient:
    settings = get_settings()

    return httpx.AsyncClient(
        base_url="https://api.mistral.ai",
        headers={
            "Authorization": f"Bearer {settings.mistral_api_key}",
            "Content-Type": "application/json",
        },
        timeout=settings.mistral_timeout_seconds,
    )


async def close_mistral_embedding_client() -> None:
    if get_mistral_embedding_client.cache_info().currsize == 0:
        return

    client = get_mistral_embedding_client()
    await client.aclose()
    get_mistral_embedding_client.cache_clear()


def validate_embedding_response(
    *,
    payload: Any,
    expected_count: int,
    expected_dimension: int,
) -> list[list[float]]:
    """Require one complete, finite vector per input index."""

    if not isinstance(payload, dict):
        raise RuntimeError("Mistral returned an invalid embeddings response")

    data = payload.get("data")

    if not isinstance(data, list) or len(data) != expected_count:
        raise RuntimeError("Mistral embedding count does not match input count")

    ordered: list[list[float] | None] = [None] * expected_count
    seen: set[int] = set()

    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError("Mistral returned an invalid embedding item")

        index = item.get("index")

        if type(index) is not int or index < 0 or index >= expected_count or index in seen:
            raise RuntimeError("Mistral returned duplicate or invalid embedding index")

        raw_vector = item.get("embedding")

        if not isinstance(raw_vector, list) or len(raw_vector) != expected_dimension:
            raise RuntimeError("Mistral embedding dimension does not match configuration")

        vector: list[float] = []

        for value in raw_vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RuntimeError("Mistral returned a nonnumeric embedding value")

            number = float(value)

            if not math.isfinite(number):
                raise RuntimeError("Mistral returned a nonfinite embedding value")

            vector.append(number)

        seen.add(index)
        ordered[index] = vector

    if seen != set(range(expected_count)):
        raise RuntimeError("Mistral embedding indices are incomplete")

    return [vector for vector in ordered if vector is not None]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    settings = get_settings()
    client = get_mistral_embedding_client()

    async def send_request(attempt: int) -> httpx.Response:
        async def call() -> httpx.Response:
            semaphore = get_embedding_semaphore()

            async with semaphore:
                return await client.post(
                    "/v1/embeddings",
                    json={
                        "model": settings.embedding_model,
                        "input": texts,
                    },
                )

        return await observe_external_call(
            provider="mistral",
            operation="embeddings",
            metadata={
                "model": settings.embedding_model,
                "attempt": attempt + 1,
            },
            call=call,
        )

    response = await request_with_retry(
        send=send_request,
        max_attempts=MAX_EMBEDDING_ATTEMPTS,
    )

    logger.info(
        "external_http_response",
        extra={
            "provider": "mistral",
            "operation": "embeddings",
            "model": settings.embedding_model,
            "status_code": response.status_code,
        },
    )

    response.raise_for_status()

    payload = cast(dict[str, Any], response.json())

    return validate_embedding_response(
        payload=payload,
        expected_count=len(texts),
        expected_dimension=settings.embedding_dimension,
    )


async def embed_query(query: str) -> list[float]:
    embeddings = await embed_texts([query])
    return embeddings[0]
