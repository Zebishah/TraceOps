import uuid

import pytest

import ops_pilot.services.retrieval as retrieval


@pytest.mark.asyncio
async def test_stale_generation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.uuid4()
    document_id = uuid.uuid4()

    old_generation = uuid.uuid4()
    new_generation = uuid.uuid4()

    candidates = [
        retrieval.RetrievalCandidate(
            chunk_id=uuid.uuid4(),
            document_id=document_id,
            chunk_index=0,
            page_number=1,
            text="OLD DOCUMENT CONTENT",
            source_filename="report.pdf",
            vector_score=0.99,
            index_generation=old_generation,
        ),
        retrieval.RetrievalCandidate(
            chunk_id=uuid.uuid4(),
            document_id=document_id,
            chunk_index=0,
            page_number=1,
            text="NEW DOCUMENT CONTENT",
            source_filename="report.pdf",
            vector_score=0.80,
            index_generation=new_generation,
        ),
    ]

    class FakeResult:
        def all(self):
            return [(document_id, new_generation)]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            return FakeResult()

    monkeypatch.setattr(
        retrieval,
        "async_session_factory",
        lambda: FakeSession(),
    )

    verified = await retrieval.filter_active_document_generations(
        organization_id=org_id,
        candidates=candidates,
    )

    assert len(verified) == 1
    assert verified[0].text == "NEW DOCUMENT CONTENT"
    assert verified[0].index_generation == new_generation


@pytest.mark.asyncio
async def test_missing_document_returns_no_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.uuid4()

    candidate = retrieval.RetrievalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=0,
        page_number=1,
        text="SHOULD NOT BE RETURNED",
        source_filename="deleted.pdf",
        vector_score=0.95,
        index_generation=uuid.uuid4(),
    )

    class FakeResult:
        def all(self):
            return []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            return FakeResult()

    monkeypatch.setattr(
        retrieval,
        "async_session_factory",
        lambda: FakeSession(),
    )

    verified = await retrieval.filter_active_document_generations(
        organization_id=org_id,
        candidates=[candidate],
    )

    assert verified == []
