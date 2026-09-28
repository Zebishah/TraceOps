import asyncio
from types import SimpleNamespace
from typing import Any

import ops_pilot.ai.reranker as reranker_module


class FakeResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {
            "data": [
                {
                    "index": 1,
                    "relevance_score": 0.90,
                },
                {
                    "index": 2,
                    "relevance_score": 0.20,
                },
                {
                    "index": 0,
                    "relevance_score": 0.10,
                },
            ]
        }


class FakeClient:
    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
    ) -> FakeResponse:
        assert url == "/v1/rerank"
        assert json["model"] == "rerank-3-lite"

        return FakeResponse()


def test_reranker_prefers_relevant_passage(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        reranker_module,
        "get_settings",
        lambda: SimpleNamespace(
            reranker_model="rerank-3-lite",
        ),
    )

    monkeypatch.setattr(
        reranker_module,
        "get_voyage_reranker_client",
        lambda: FakeClient(),
    )

    passages = [
        "The weather is sunny today.",
        "The document describes syntactic tests.",
        "This section explains copyright.",
    ]

    scores = asyncio.run(
        reranker_module.rerank_passages(
            query="What tests are described?",
            passages=passages,
        )
    )

    assert scores == [0.10, 0.90, 0.20]

    best_index = max(
        range(len(scores)),
        key=scores.__getitem__,
    )

    assert best_index == 1
