import asyncio
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.incident_memory_indexing as indexing_module
from ops_pilot.models.incident_memory import IncidentMemory


def test_build_memory_embedding_text() -> None:
    memory = IncidentMemory(
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        subject_customer_id=None,
        category="payment",
        summary="Customer was charged twice.",
        resolution="Duplicate charge was refunded.",
    )

    text = indexing_module.build_memory_embedding_text(
        memory,
    )

    assert text == (
        "Category: payment\n"
        "Incident summary: Customer was charged twice.\n"
        "Resolution: Duplicate charge was refunded."
    )


def test_index_incident_memory_upserts_memory(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    memory_id = uuid.uuid4()

    memory = IncidentMemory(
        id=memory_id,
        organization_id=organization_id,
        incident_id=incident_id,
        subject_customer_id=None,
        category="payment",
        summary="Customer was charged twice.",
        resolution="Duplicate charge was refunded.",
    )

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    async def fake_get_incident_memory(
        **kwargs: object,
    ) -> IncidentMemory:
        return memory

    async def fake_ensure_memory_collection() -> None:
        return None

    async def fake_embed_texts(
        texts: list[str],
    ) -> list[list[float]]:
        assert len(texts) == 1

        return [
            [0.1] * 1024,
        ]

    class FakeClient:
        async def upsert(
            self,
            *,
            collection_name: str,
            points: list[object],
            wait: bool,
        ) -> None:
            assert collection_name == ("ops_pilot_incident_memories_v1")

            assert len(points) == 1
            assert wait is True

    monkeypatch.setattr(
        indexing_module,
        "get_incident_memory",
        fake_get_incident_memory,
    )

    monkeypatch.setattr(
        indexing_module,
        "ensure_memory_collection",
        fake_ensure_memory_collection,
    )

    monkeypatch.setattr(
        indexing_module,
        "embed_texts",
        fake_embed_texts,
    )

    monkeypatch.setattr(
        indexing_module,
        "get_qdrant_client",
        lambda: FakeClient(),
    )

    monkeypatch.setattr(
        indexing_module,
        "get_settings",
        lambda: SimpleNamespace(
            qdrant_memory_collection_name=("ops_pilot_incident_memories_v1"),
            embedding_model="mistral-embed",
        ),
    )

    result = asyncio.run(
        indexing_module.index_incident_memory(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )
    )

    assert result == 1

    cast(AsyncMock, session.rollback).assert_awaited_once()
