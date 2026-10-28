from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qdrant_client import models

from ops_pilot.services import project_knowledge_ingestion
from ops_pilot.services.project_knowledge_ingestion import (
    create_project_knowledge_chunks,
    extract_markdown_sections,
)


@pytest.fixture(autouse=True)
def isolate_project_knowledge_rebuild_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit tests must never connect to a real PostgreSQL DB."""

    @asynccontextmanager
    async def fake_lock() -> AsyncIterator[None]:
        yield

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "acquire_project_knowledge_rebuild_lock",
        fake_lock,
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
@pytest.mark.parametrize("alias_already_exists", [False, True])
async def test_index_project_knowledge_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    alias_already_exists: bool,
) -> None:
    """Publishing must preserve old data and atomically update the alias."""

    knowledge_file = tmp_path / "architecture.md"
    knowledge_file.write_text(
        "# Architecture\n\nOpsPilot uses LangGraph for incident workflows.",
        encoding="utf-8",
    )

    async def fake_embed_texts(
        texts: list[str],
    ) -> list[list[float]]:
        assert texts == ["OpsPilot uses LangGraph for incident workflows."]
        return [[0.1, 0.2, 0.3]]

    legacy_name = "ops_pilot_project_knowledge_v1"
    active_alias = f"{legacy_name}__active"

    fake_settings = SimpleNamespace(
        embedding_model="mistral-embed",
        embedding_dimension=3,
        qdrant_project_knowledge_collection_name=legacy_name,
    )

    fake_client = AsyncMock()
    fake_client.count.return_value = SimpleNamespace(count=1)

    old_aliases = (
        [
            SimpleNamespace(
                alias_name=active_alias,
                collection_name=f"{legacy_name}__v_previous",
            )
        ]
        if alias_already_exists
        else []
    )

    # After publishing, the new collection's version name
    # will be obtained from the actual alias operation.
    async def get_aliases():
        if fake_client.update_collection_aliases.await_count == 0:
            return SimpleNamespace(aliases=old_aliases)

        operations = fake_client.update_collection_aliases.await_args.kwargs[
            "change_aliases_operations"
        ]

        created = next(
            operation.create_alias
            for operation in operations
            if isinstance(operation, models.CreateAliasOperation)
        )

        return SimpleNamespace(
            aliases=[
                SimpleNamespace(
                    alias_name=created.alias_name,
                    collection_name=created.collection_name,
                )
            ]
        )

    fake_client.get_aliases.side_effect = get_aliases

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "embed_texts",
        fake_embed_texts,
    )
    monkeypatch.setattr(
        project_knowledge_ingestion,
        "get_qdrant_client",
        lambda: fake_client,
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

    # D01: Never destroy the currently searchable collection.
    fake_client.delete_collection.assert_not_awaited()

    fake_client.create_collection.assert_awaited_once()

    created_collection = fake_client.create_collection.await_args.kwargs["collection_name"]

    assert created_collection.startswith(f"{legacy_name}__v_")
    assert created_collection != legacy_name

    assert fake_client.create_payload_index.await_count == 2

    fake_client.upsert.assert_awaited_once()

    upload = fake_client.upsert.await_args.kwargs

    assert upload["collection_name"] == created_collection
    assert upload["wait"] is True

    points = upload["points"]

    assert len(points) == 1
    assert points[0].payload == {
        "source": "architecture.md",
        "section": "Architecture",
        "chunk_index": 0,
        "text": "OpsPilot uses LangGraph for incident workflows.",
        "embedding_model": "mistral-embed",
    }

    fake_client.count.assert_awaited_once_with(
        collection_name=created_collection,
        exact=True,
    )

    fake_client.update_collection_aliases.assert_awaited_once()

    operations = fake_client.update_collection_aliases.await_args.kwargs[
        "change_aliases_operations"
    ]

    creates = [
        operation.create_alias
        for operation in operations
        if isinstance(operation, models.CreateAliasOperation)
    ]

    deletes = [
        operation.delete_alias
        for operation in operations
        if isinstance(operation, models.DeleteAliasOperation)
    ]

    assert len(creates) == 1
    assert creates[0].alias_name == active_alias
    assert creates[0].collection_name == created_collection

    assert len(deletes) == (1 if alias_already_exists else 0)

    if deletes:
        assert deletes[0].alias_name == active_alias

    # Qdrant alias publication must occur as one operation.
    assert fake_client.update_collection_aliases.await_count == 1


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


@pytest.mark.anyio
async def test_qdrant_upload_failure_preserves_existing_knowledge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unsuccessful rebuild must never publish partial knowledge."""

    (tmp_path / "architecture.md").write_text(
        "# Architecture\n\nOpsPilot uses FastAPI.",
        encoding="utf-8",
    )

    async def fake_embed_texts(
        texts: list[str],
    ) -> list[list[float]]:
        assert texts == ["OpsPilot uses FastAPI."]
        return [[0.1, 0.2, 0.3]]

    legacy_name = "ops_pilot_project_knowledge_v1"
    active_alias = f"{legacy_name}__active"
    old_collection = f"{legacy_name}__v_previous"

    fake_settings = SimpleNamespace(
        embedding_model="mistral-embed",
        embedding_dimension=3,
        qdrant_project_knowledge_collection_name=legacy_name,
    )

    fake_client = AsyncMock()

    fake_client.get_aliases.return_value = SimpleNamespace(
        aliases=[
            SimpleNamespace(
                alias_name=active_alias,
                collection_name=old_collection,
            )
        ]
    )

    fake_client.upsert.side_effect = RuntimeError("Simulated Qdrant upload failure")

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "embed_texts",
        fake_embed_texts,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "get_qdrant_client",
        lambda: fake_client,
    )

    monkeypatch.setattr(
        project_knowledge_ingestion,
        "get_settings",
        lambda: fake_settings,
    )

    with pytest.raises(
        RuntimeError,
        match="Simulated Qdrant upload failure",
    ):
        await project_knowledge_ingestion.index_project_knowledge_directory(
            directory=tmp_path,
        )

    fake_client.upsert.assert_awaited_once()

    # Failure must not destroy the old collection.
    fake_client.delete_collection.assert_not_awaited()

    # Failure must not publish incomplete replacement data.
    fake_client.update_collection_aliases.assert_not_awaited()

    # The original alias configuration is unchanged.
    fake_client.get_aliases.assert_not_awaited()

    fake_client.count.assert_not_awaited()
