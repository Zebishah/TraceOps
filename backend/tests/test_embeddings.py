import asyncio
from types import SimpleNamespace
from typing import Any

import ops_pilot.ai.embeddings as embeddings_module


class FakeResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {
            "data": [
                {
                    "index": 1,
                    "embedding": [0.2] * 1024,
                },
                {
                    "index": 0,
                    "embedding": [0.1] * 1024,
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
        assert url == "/v1/embeddings"
        assert json["model"] == "mistral-embed"

        return FakeResponse()


def test_embed_texts_returns_vectors_in_input_order(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        embeddings_module,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_model="mistral-embed",
            embedding_dimension=1024,
        ),
    )

    monkeypatch.setattr(
        embeddings_module,
        "get_mistral_embedding_client",
        lambda: FakeClient(),
    )

    vectors = asyncio.run(
        embeddings_module.embed_texts(
            [
                "first text",
                "second text",
            ]
        )
    )

    assert len(vectors) == 2
    assert len(vectors[0]) == 1024

    assert vectors[0][0] == 0.1
    assert vectors[1][0] == 0.2
