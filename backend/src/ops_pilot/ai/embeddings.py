import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from ops_pilot.core.config import get_settings


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()

    return SentenceTransformer(
        settings.embedding_model,
        token=settings.hf_token,
    )


def _embed_texts_sync(
    texts: list[str],
) -> list[list[float]]:
    settings = get_settings()
    model = get_embedding_model()

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        truncate_dim=settings.embedding_dimension,
        show_progress_bar=False,
    )

    return [[float(value) for value in vector] for vector in embeddings]


async def embed_texts(
    texts: list[str],
) -> list[list[float]]:
    if not texts:
        return []

    return await asyncio.to_thread(
        _embed_texts_sync,
        texts,
    )


def _embed_query_sync(
    query: str,
) -> list[float]:
    settings = get_settings()
    model = get_embedding_model()

    embedding = model.encode(
        query,
        prompt_name="query",
        normalize_embeddings=True,
        truncate_dim=settings.embedding_dimension,
        show_progress_bar=False,
    )

    return [float(value) for value in embedding]


async def embed_query(
    query: str,
) -> list[float]:
    return await asyncio.to_thread(
        _embed_query_sync,
        query,
    )
