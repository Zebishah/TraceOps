import asyncio

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import ops_pilot.ai.generation as generation_module


def test_generate_grounded_answer_uses_langchain_model(
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    async def fake_model(prompt_value):
        messages = prompt_value.to_messages()

        captured["system"] = str(
            messages[0].content,
        )

        captured["human"] = str(
            messages[-1].content,
        )

        return AIMessage(
            content=("Duplicate charges should be refunded after verification [SOURCE 1].")
        )

    monkeypatch.setattr(
        generation_module,
        "get_chat_model",
        lambda: RunnableLambda(fake_model),
    )

    answer = asyncio.run(
        generation_module.generate_grounded_answer(
            question="What should happen after a duplicate charge?",
            context=("[SOURCE 1]\nDuplicate charges should be refunded after verification."),
        )
    )

    assert answer == "Duplicate charges should be refunded after verification [SOURCE 1]."

    assert "Use only the supplied evidence" in captured["system"]

    assert "What should happen after a duplicate charge?" in captured["human"]

    assert "Duplicate charges should be refunded" in captured["human"]


def test_generate_grounded_answer_rejects_empty_response(
    monkeypatch,
) -> None:
    async def fake_model(prompt_value):
        return AIMessage(
            content="   ",
        )

    monkeypatch.setattr(
        generation_module,
        "get_chat_model",
        lambda: RunnableLambda(fake_model),
    )

    with pytest.raises(
        RuntimeError,
        match="LLM returned an empty answer",
    ):
        asyncio.run(
            generation_module.generate_grounded_answer(
                question="Test question",
                context="[SOURCE 1] Test evidence",
            )
        )
