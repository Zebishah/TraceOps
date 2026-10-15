import uuid
from unittest.mock import AsyncMock

import pytest

from ops_pilot.evaluation import retrieval
from ops_pilot.schemas.retrieval import (
    RetrievalResult,
)


@pytest.mark.anyio
async def test_retrieval_evaluation_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_retrieve_document_chunks(
        *,
        organization_id: uuid.UUID,
        query: str,
        limit: int,
    ) -> list[RetrievalResult]:
        del organization_id
        del limit

        text_by_query = {
            "charged twice": (
                "Duplicate payment policy. "
                "Verify both transactions and refund "
                "only the duplicate charge."
            ),
            "human approval": ("Human approval is required before executing a refund."),
            "duplicate webhook": ("A duplicate webhook can cause repeated payment processing."),
            "cannot sign in": ("Authentication incidents include users who cannot sign in."),
            "high or critical": (
                "HIGH indicates serious impact. CRITICAL indicates severe or widespread impact."
            ),
        }

        selected = next(text for key, text in text_by_query.items() if key in query)

        return [
            RetrievalResult(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                chunk_index=0,
                page_number=1,
                text=selected,
                source_filename="policy.pdf",
                vector_score=0.90,
                reranker_score=0.95,
            ),
            RetrievalResult(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                chunk_index=1,
                page_number=1,
                text="Supporting context.",
                source_filename="policy.pdf",
                vector_score=0.80,
                reranker_score=0.80,
            ),
        ]

    mock = AsyncMock(
        side_effect=fake_retrieve_document_chunks,
    )

    monkeypatch.setattr(
        retrieval,
        "retrieve_document_chunks",
        mock,
    )

    result = await retrieval.evaluate_document_retrieval(
        organization_id=uuid.uuid4(),
    )

    assert result.total_cases == 3
    assert result.passed_cases == 3
    assert result.failed_cases == 0
    assert result.pass_rate == 1.0
    assert mock.await_count == 3
