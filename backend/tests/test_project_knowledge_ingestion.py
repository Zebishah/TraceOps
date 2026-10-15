from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ops_pilot.services import project_knowledge_ingestion
from ops_pilot.services.project_knowledge_ingestion import (
    create_project_knowledge_chunks,
    extract_markdown_sections,
)


def test_extract_markdown_sections() -> None:
    text = """
# Overview

OpsPilot investigates incidents.

# LangGraph

LangGraph controls the investigation workflow.

# n8n

n8n handles business automation.
"""

    sections = extract_markdown_sections(
        source="architecture.md",
        text=text,
    )

    assert sections == [
        (
            "Overview",
            "OpsPilot investigates incidents.",
        ),
        (
            "LangGraph",
            "LangGraph controls the investigation workflow.",
        ),
        (
            "n8n",
            "n8n handles business automation.",
        ),
    ]


def test_project_knowledge_chunks_are_deterministic() -> None:
    text = """
# Retrieval

OpsPilot uses vector retrieval and reranking.
"""

    first = create_project_knowledge_chunks(
        source="architecture.md",
        text=text,
    )

    second = create_project_knowledge_chunks(
        source="architecture.md",
        text=text,
    )

    assert len(first) == 1
    assert len(second) == 1

    assert first[0].id == second[0].id

    assert first[0].source == "architecture.md"
    assert first[0].section == "Retrieval"
    assert first[0].chunk_index == 0
    assert first[0].text == ("OpsPilot uses vector retrieval and reranking.")


@pytest.mark.anyio
async def test_index_project_knowledge_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    knowledge_file = tmp_path / "architecture.md"

    knowledge_file.write_text(
        "# Architecture\n\nOpsPilot uses LangGraph for incident workflows.",
        encoding="utf-8",
    )

    fake_vectors = [
        [0.1, 0.2, 0.3],
    ]

    async def fake_embed_texts(
        texts: list[str],
    ) -> list[list[float]]:
        assert texts == ["OpsPilot uses LangGraph for incident workflows."]

        return fake_vectors

    fake_qdrant_client = AsyncMock()
    fake_qdrant_client.collection_exists.return_value = True
    fake_settings = SimpleNamespace(
        embedding_model="mistral-embed",
        qdrant_project_knowledge_collection_name=("ops_pilot_project_knowledge_v1"),
    )

    ensure_collection = AsyncMock()

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "ensure_project_knowledge_collection",
        ensure_collection,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "embed_texts",
        fake_embed_texts,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "get_qdrant_client",
        lambda: fake_qdrant_client,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "get_settings",
        lambda: fake_settings,
    )

    result = await project_knowledge_ingestion.index_project_knowledge_directory(
        directory=tmp_path,
    )

    assert result == 1
    fake_qdrant_client.collection_exists.assert_awaited_once_with(
        collection_name=("ops_pilot_project_knowledge_v1"),
    )

    fake_qdrant_client.delete_collection.assert_awaited_once_with(
        collection_name=("ops_pilot_project_knowledge_v1"),
    )
    ensure_collection.assert_awaited_once()

    fake_qdrant_client.upsert.assert_awaited_once()

    call = fake_qdrant_client.upsert.await_args

    assert call.kwargs["collection_name"] == ("ops_pilot_project_knowledge_v1")

    points = call.kwargs["points"]

    assert len(points) == 1

    assert points[0].payload == {
        "source": "architecture.md",
        "section": "Architecture",
        "chunk_index": 0,
        "text": ("OpsPilot uses LangGraph for incident workflows."),
        "embedding_model": "mistral-embed",
    }


@pytest.mark.anyio
async def test_index_project_knowledge_creates_collection_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    knowledge_file = tmp_path / "architecture.md"

    knowledge_file.write_text(
        "# Architecture\n\nOpsPilot uses FastAPI.",
        encoding="utf-8",
    )

    async def fake_embed_texts(
        texts: list[str],
    ) -> list[list[float]]:
        assert texts == ["OpsPilot uses FastAPI."]

        return [
            [0.1, 0.2, 0.3],
        ]

    fake_qdrant_client = AsyncMock()

    fake_qdrant_client.collection_exists.return_value = False

    fake_settings = SimpleNamespace(
        embedding_model="mistral-embed",
        qdrant_project_knowledge_collection_name=("ops_pilot_project_knowledge_v1"),
    )

    ensure_collection = AsyncMock()

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "ensure_project_knowledge_collection",
        ensure_collection,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "embed_texts",
        fake_embed_texts,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "get_qdrant_client",
        lambda: fake_qdrant_client,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "get_settings",
        lambda: fake_settings,
    )

    result = await project_knowledge_ingestion.index_project_knowledge_directory(
        directory=tmp_path,
    )

    assert result == 1

    fake_qdrant_client.delete_collection.assert_not_awaited()

    ensure_collection.assert_awaited_once()

    fake_qdrant_client.upsert.assert_awaited_once()


@pytest.mark.anyio
async def test_embedding_failure_preserves_existing_knowledge_collection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    knowledge_file = tmp_path / "architecture.md"

    knowledge_file.write_text(
        "# Architecture\n\nOpsPilot uses FastAPI.",
        encoding="utf-8",
    )

    async def failing_embed_texts(
        texts: list[str],
    ) -> list[list[float]]:
        assert texts == ["OpsPilot uses FastAPI."]

        raise RuntimeError("Embedding provider unavailable")

    fake_qdrant_client = AsyncMock()

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "embed_texts",
        failing_embed_texts,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "get_qdrant_client",
        lambda: fake_qdrant_client,
    )

    with pytest.raises(
        RuntimeError,
        match="Embedding provider unavailable",
    ):
        await project_knowledge_ingestion.index_project_knowledge_directory(
            directory=tmp_path,
        )

    fake_qdrant_client.collection_exists.assert_not_awaited()

    fake_qdrant_client.delete_collection.assert_not_awaited()

    fake_qdrant_client.upsert.assert_not_awaited()


@pytest.mark.anyio
async def test_index_project_knowledge_rejects_empty_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        RuntimeError,
        match="No markdown files found",
    ):
        await project_knowledge_ingestion.index_project_knowledge_directory(
            directory=tmp_path,
        )
