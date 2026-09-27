import asyncio

from ops_pilot.ai.reranker import rerank_passages


def test_reranker_prefers_relevant_passage() -> None:
    query = "What types of tests are described?"

    passages = [
        "The weather is sunny today.",
        ("The document describes syntactic tests, import rejection tests, and semantic tests."),
        "This section explains document copyright.",
    ]

    scores = asyncio.run(
        rerank_passages(
            query=query,
            passages=passages,
        )
    )

    assert len(scores) == 3

    best_index = max(
        range(len(scores)),
        key=scores.__getitem__,
    )

    assert best_index == 1
