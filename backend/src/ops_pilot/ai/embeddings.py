import asyncio
import logging
from functools import lru_cache
from typing import Any, cast

import httpx

from ops_pilot.core.config import get_settings
from ops_pilot.integrations.observability import (
    observe_external_call,
)

logger = logging.getLogger(__name__)
MAX_EMBEDDING_ATTEMPTS = 4
BASE_RETRY_DELAY_SECONDS = 1.0


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


async def embed_texts(
    texts: list[str],
) -> list[list[float]]:
    if not texts:
        return []

    settings = get_settings()
    client = get_mistral_embedding_client()

    response: httpx.Response | None = None

    for attempt in range(
        MAX_EMBEDDING_ATTEMPTS,
    ):

        async def send_request() -> httpx.Response:
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
        if response.status_code != 429:
            break

        if attempt == MAX_EMBEDDING_ATTEMPTS - 1:
            break

        await asyncio.sleep(
            _retry_delay_seconds(
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
