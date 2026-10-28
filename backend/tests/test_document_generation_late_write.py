"""D03: Late Qdrant writes must not expose stale document content."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.retrieval as retrieval


@pytest.mark.asyncio
async def test_late_old_generation_cannot_override_active_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()

    old_generation = uuid.uuid4()
    new_generation = uuid.uuid4()

    old_chunk_id = uuid.uuid4()
    new_chunk_id = uuid.uuid4()

    # Simulated PostgreSQL state:
    # a newer indexing dispatch has already published.
    active_generation = new_generation

    # Simulated Qdrant storage.
    points: list[SimpleNamespace] = []

    def write_point(
        *,
        chunk_id: uuid.UUID,
        generation: uuid.UUID,
        text: str,
        score: float,
    ) -> None:
        points.append(
            SimpleNamespace(
                id=str(chunk_id),
                score=score,
                payload={
                    "organization_id": str(organization_id),
                    "document_id": str(document_id),
                    "index_generation": str(generation),
                    "chunk_index": 0,
                    "page_number": 1,
                    "text": text,
                    "source_filename": "policy.pdf",
                },
            )
        )

    # New worker finishes first.
    write_point(
        chunk_id=new_chunk_id,
        generation=new_generation,
        text="CURRENT REFUND POLICY",
        score=0.75,
    )

    # Old worker's delayed Qdrant write completes afterward.
    # Its similarity score is intentionally higher.
    write_point(
        chunk_id=old_chunk_id,
        generation=old_generation,
        text="OUTDATED REFUND POLICY",
        score=0.99,
    )

    class FakeDatabaseResult:
        def all(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
            return [(document_id, active_generation)]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def execute(self, statement: object) -> FakeDatabaseResult:
            return FakeDatabaseResult()

    monkeypatch.setattr(
        retrieval,
        "async_session_factory",
        lambda: FakeSession(),
    )

    async def fake_pages(*, organization_id: uuid.UUID):
        return [([new_generation], [])]

    monkeypatch.setattr(retrieval, "_eligible_generation_pages", fake_pages)

    monkeypatch.setattr(
        retrieval,
        "get_settings",
        lambda: SimpleNamespace(
            qdrant_collection_name="test_documents",
            retrieval_candidate_limit=12,
        ),
    )

    monkeypatch.setattr(
        retrieval,
        "embed_query",
        AsyncMock(return_value=[0.1, 0.2]),
    )

    async def query_points(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            points=sorted(
                points,
                key=lambda point: point.score,
                reverse=True,
            )
        )

    monkeypatch.setattr(
        retrieval,
        "get_qdrant_client",
        lambda: SimpleNamespace(
            query_points=query_points,
        ),
    )

    rerank = AsyncMock(return_value=[0.95])

    monkeypatch.setattr(
        retrieval,
        "rerank_passages",
        rerank,
    )

    results = await retrieval.retrieve_document_chunks(
        organization_id=organization_id,
        query="What is the refund policy?",
        limit=5,
    )

    assert len(results) == 1

    assert results[0].chunk_id == new_chunk_id
    assert results[0].document_id == document_id
    assert results[0].text == "CURRENT REFUND POLICY"

    assert all("OUTDATED" not in result.text for result in results)

    # The stale point must also be excluded BEFORE reranking.
    rerank.assert_awaited_once()

    passages = rerank.await_args.kwargs["passages"]

    assert passages == ["CURRENT REFUND POLICY"]


@pytest.mark.asyncio
async def test_only_stale_points_return_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()
    old_generation = uuid.uuid4()
    new_generation = uuid.uuid4()

    candidate = retrieval.RetrievalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=document_id,
        chunk_index=0,
        page_number=1,
        text="STALE DOCUMENT",
        source_filename="old.pdf",
        vector_score=0.99,
        index_generation=old_generation,
    )

    class FakeResult:
        def all(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
            return [(document_id, new_generation)]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def execute(self, statement: object) -> FakeResult:
            return FakeResult()

    monkeypatch.setattr(
        retrieval,
        "async_session_factory",
        lambda: FakeSession(),
    )

    results = await retrieval.filter_active_document_generations(
        organization_id=organization_id,
        candidates=[candidate],
    )

    assert results == []
