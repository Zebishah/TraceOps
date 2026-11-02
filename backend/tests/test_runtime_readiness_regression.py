import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import ops_pilot.api.routes.health as health
import ops_pilot.services.retrieval as retrieval


@pytest.mark.asyncio
@pytest.mark.parametrize("exists", [True, False])
async def test_qdrant_readiness_checks_collection_existence(
    monkeypatch: pytest.MonkeyPatch,
    exists: bool,
) -> None:
    collection_exists = AsyncMock(return_value=exists)

    monkeypatch.setattr(
        health,
        "get_settings",
        lambda: SimpleNamespace(
            health_dependency_timeout_seconds=1.0,
            qdrant_collection_name="documents",
        ),
    )
    monkeypatch.setattr(
        health,
        "get_qdrant_client",
        lambda: SimpleNamespace(collection_exists=collection_exists),
    )

    healthy, duration_ms = await health.check_qdrant()

    assert healthy is exists
    assert duration_ms >= 0
    collection_exists.assert_awaited_once_with(
        collection_name="documents",
    )


@pytest.mark.asyncio
async def test_slow_dependency_fails_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health,
        "get_settings",
        lambda: SimpleNamespace(
            health_dependency_timeout_seconds=0.01,
        ),
    )

    async def slow_operation() -> bool:
        await asyncio.Event().wait()
        return True

    healthy, duration_ms = await health._check_dependency(
        provider="slow-service",
        operation=slow_operation,
    )

    assert healthy is False
    assert duration_ms >= 0


@pytest.mark.asyncio
async def test_dependency_exception_fails_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health,
        "get_settings",
        lambda: SimpleNamespace(
            health_dependency_timeout_seconds=1.0,
        ),
    )

    healthy, _duration_ms = await health._check_dependency(
        provider="broken-service",
        operation=AsyncMock(side_effect=ConnectionError("unavailable")),
    )

    assert healthy is False


@pytest.mark.asyncio
async def test_readiness_starts_dependency_checks_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: set[str] = set()
    all_started = asyncio.Event()

    async def check(name: str) -> tuple[bool, float]:
        started.add(name)

        if len(started) == 3:
            all_started.set()

        await asyncio.wait_for(all_started.wait(), timeout=1.0)
        return True, 1.0

    monkeypatch.setattr(
        health,
        "check_database",
        lambda: check("database"),
    )
    monkeypatch.setattr(
        health,
        "check_redis",
        lambda: check("redis"),
    )
    monkeypatch.setattr(
        health,
        "check_qdrant",
        lambda: check("qdrant"),
    )

    response = await health.readiness_check()

    assert response.status_code == 200
    assert started == {"database", "redis", "qdrant"}


@pytest.mark.asyncio
async def test_empty_documents_skip_embedding_and_vector_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    eligible_pages = AsyncMock(return_value=[])
    embed_query = AsyncMock()
    vector_client = Mock()

    monkeypatch.setattr(
        retrieval,
        "_eligible_generation_pages",
        eligible_pages,
    )
    monkeypatch.setattr(retrieval, "embed_query", embed_query)
    monkeypatch.setattr(
        retrieval,
        "get_qdrant_client",
        vector_client,
    )

    result = await retrieval.retrieve_document_chunks(
        organization_id=organization_id,
        query="What is our refund policy?",
    )

    assert result == []
    eligible_pages.assert_awaited_once_with(
        organization_id=organization_id,
    )
    embed_query.assert_not_awaited()
    vector_client.assert_not_called()
