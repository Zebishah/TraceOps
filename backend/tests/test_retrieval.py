import uuid

from ops_pilot.schemas.retrieval import RetrievalResult


def test_retrieval_result_schema() -> None:
    result = RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=3,
        page_number=2,
        text="Refunds are allowed within 30 days.",
        source_filename="refund-policy.pdf",
        vector_score=0.82,
        reranker_score=4.25,
    )

    assert result.chunk_index == 3
    assert result.page_number == 2
    assert result.vector_score == 0.82
    assert result.reranker_score == 4.25
