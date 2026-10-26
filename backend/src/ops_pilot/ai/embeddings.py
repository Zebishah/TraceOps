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

MAX_CONCURRENT_EMBEDDING_REQUESTS = 3

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


async def embed_texts(
    texts: list[str],
) -> list[list[float]]:
    if not texts:
        return []

    settings = get_settings()
    client = get_mistral_embedding_client()

    response: httpx.Response | None = None

    for attempt in range(
        MAX_CONCURRENT_EMBEDDING_REQUESTS,
    ):

        async def send_request() -> httpx.Response:
            semaphore = get_embedding_semaphore()

            async with semaphore:
                return await client.post(
                    "/v1/embeddings",
                    json={
                        "model": settings.embedding_model,
                        "input": texts,
                    },
                )

        response = await observe_external_call(
            provider="mistral",
            operation="embeddings",
            metadata={
                "model": settings.embedding_model,
                "attempt": attempt + 1,
            },
            call=send_request,
        )
        logger.info(
            "external_http_response",
            extra={
                "provider": "mistral",
                "operation": "embeddings",
                "model": settings.embedding_model,
                "attempt": attempt + 1,
                "status_code": response.status_code,
            },
        )
        if not should_retry_response(response):
            break

        if attempt == MAX_CONCURRENT_EMBEDDING_REQUESTS - 1:
            break

        await asyncio.sleep(
            retry_delay_seconds(
                response=response,
                attempt=attempt,
            )
        )

    if response is None:
        raise RuntimeError("Mistral embeddings did not return a response")

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
        raise RuntimeError("Mistral returned an invalid embeddings response")

    ordered = sorted(
        data,
        key=lambda item: int(
            item["index"],
        ),
    )

    embeddings: list[list[float]] = []

    for item in ordered:
        vector = [float(value) for value in item["embedding"]]

        if len(vector) != settings.embedding_dimension:
            raise RuntimeError("Mistral embedding dimension does not match configuration")

        embeddings.append(
            vector,
        )

    if len(embeddings) != len(texts):
        raise RuntimeError("Mistral embedding count does not match input count")

    return embeddings


async def embed_query(
    query: str,
) -> list[float]:
    embeddings = await embed_texts(
        [query],
    )

    return embeddings[0]
