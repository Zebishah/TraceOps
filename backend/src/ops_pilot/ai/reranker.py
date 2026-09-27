import asyncio
from functools import lru_cache
from typing import cast

from sentence_transformers import CrossEncoder

from ops_pilot.core.config import get_settings


@lru_cache
def get_reranker() -> CrossEncoder:
    settings = get_settings()

    return cast(
        CrossEncoder,
        CrossEncoder(
            settings.reranker_model,
            token=settings.hf_token,
        ),
    )


def _rerank_sync(
    *,
    query: str,
    passages: list[str],
) -> list[float]:
    if not passages:
        return []

    model = get_reranker()

    pairs = [(query, passage) for passage in passages]

    scores = model.predict(
        pairs,
        show_progress_bar=False,
    )

    return [float(score) for score in scores]


async def rerank_passages(
    *,
    query: str,
    passages: list[str],
) -> list[float]:
    return await asyncio.to_thread(
        _rerank_sync,
        query=query,
        passages=passages,
    )
