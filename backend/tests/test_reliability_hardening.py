import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.ai.embeddings as embeddings_module
import ops_pilot.services.document_indexing as indexing_module
from ops_pilot.core.exceptions import DocumentProcessingError


def make_chunk(
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=organization_id,
        document_id=document_id,
        text="Verified payment refund policy",
        chunk_index=0,
        page_number=1,
        source_filename="policy.pdf",
        document_checksum="checksum-test",
    )


def setup_indexing(monkeypatch, chunks):
    client = SimpleNamespace(
        scroll=AsyncMock(return_value=([], None)),
        upsert=AsyncMock(),
        delete=AsyncMock(),
    )

    monkeypatch.setattr(
        indexing_module,
        "prepare_document_chunks",
        AsyncMock(return_value=chunks),
    )
    monkeypatch.setattr(
        indexing_module,
        "ensure_document_collection",
        AsyncMock(),
    )
    monkeypatch.setattr(
        indexing_module,
        "embed_texts",
        AsyncMock(return_value=[[0.1] * 1024 for _ in chunks]),
    )
    monkeypatch.setattr(
        indexing_module,
        "get_settings",
        lambda: SimpleNamespace(
            qdrant_collection_name="test_documents",
            embedding_model="mistral-embed",
        ),
    )
    monkeypatch.setattr(
        indexing_module,
        "get_qdrant_client",
        lambda: client,
    )

    return client


def test_reindex_does_not_delete_before_failed_upsert(
    monkeypatch,
):
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()

    chunk = make_chunk(organization_id, document_id)
    client = setup_indexing(monkeypatch, [chunk])

    old_id = str(uuid.uuid4())

    client.scroll.return_value = (
        [SimpleNamespace(id=old_id)],
        None,
    )
    client.upsert.side_effect = RuntimeError("Qdrant upload failed")

    with pytest.raises(DocumentProcessingError):
        asyncio.run(
            indexing_module._index_document_unlocked(
                generation_id=uuid.uuid4(),
                session=AsyncMock(),
                organization_id=organization_id,
                document_id=document_id,
            )
        )

    client.delete.assert_not_awaited()


def test_indexing_without_dispatch_is_rejected():
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()

    with pytest.raises(
        DocumentProcessingError,
        match="requires an active job and dispatch ID",
    ):
        asyncio.run(
            indexing_module.index_document(
                session=AsyncMock(),
                organization_id=organization_id,
                document_id=document_id,
            )
        )


def test_generation_indexing_does_not_delete_other_generations(
    monkeypatch,
):
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()
    generation_id = uuid.uuid4()

    chunk = make_chunk(organization_id, document_id)
    client = setup_indexing(monkeypatch, [chunk])

    old_id = str(uuid.uuid4())

    client.scroll.return_value = (
        [SimpleNamespace(id=old_id)],
        None,
    )

    count = asyncio.run(
        indexing_module._index_document_unlocked(
            session=AsyncMock(),
            organization_id=organization_id,
            document_id=document_id,
            generation_id=generation_id,
        )
    )

    assert count == 1

    client.upsert.assert_awaited_once()

    # A generation-specific write must never delete
    # points from another generation.
    client.delete.assert_not_awaited()

    uploaded_points = client.upsert.await_args.kwargs["points"]

    assert len(uploaded_points) == 1

    expected_point_id = uuid.uuid5(
        chunk.id,
        str(generation_id),
    )

    assert str(uploaded_points[0].id) == str(expected_point_id)

    assert uploaded_points[0].payload["index_generation"] == str(generation_id)


def test_embedding_concurrency_limit():
    async def scenario():
        semaphore = asyncio.Semaphore(2)
        active = 0
        maximum = 0

        async def worker():
            nonlocal active, maximum

            async with semaphore:
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(worker() for _ in range(10)))

        assert maximum <= 2

    asyncio.run(scenario())


def test_embedding_semaphore_is_reused():
    first = embeddings_module.get_embedding_semaphore()
    second = embeddings_module.get_embedding_semaphore()

    assert first is second
