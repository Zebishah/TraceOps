import asyncio

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import ops_pilot.ai.incident_analyzer as analyzer_module
import ops_pilot.ai.incident_recommender as recommender_module
from ops_pilot.ai.output_validation import (
    InvalidAIOutputError,
    run_with_output_retry,
    validate_text_response,
)


def validate(
    text: str,
    *,
    finish_reason: str = "stop",
    sources: int = 1,
    tools: tuple[bool, ...] = (True, False),
    memories: int = 1,
) -> str:
    return validate_text_response(
        AIMessage(
            content=text,
            response_metadata={"finish_reason": finish_reason},
        ),
        source_count=sources,
        tool_successes=tools,
        memory_count=memories,
        empty_error="Empty response",
    )


def test_accepts_existing_source_tool_and_memory() -> None:
    text = "Evidence [SOURCE 1] [TOOL 1]; historical context [MEMORY 1]."

    assert validate(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Unsupported source [SOURCE 2].",
        "Unsupported tool [TOOL 3].",
        "Failed tool [TOOL 2].",
        "Unsupported memory [MEMORY 2].",
        "Invalid index [SOURCE 0].",
        "Invalid range [SOURCE 1-2].",
        "Combined labels [TOOL 1, 2].",
        "Invalid format [source 1].",
        "Unclosed citation [SOURCE 1",
        "Missing index [MEMORY].",
    ],
)
def test_rejects_invalid_citations(text: str) -> None:
    with pytest.raises(InvalidAIOutputError):
        validate(text)


def test_preserves_original_tool_numbering() -> None:
    assert (
        validate(
            "Verified record [TOOL 2].",
            tools=(False, True),
        )
        == "Verified record [TOOL 2]."
    )


@pytest.mark.parametrize(
    "reason",
    ["length", "max_tokens", "max_output_tokens", "content_filter"],
)
def test_rejects_incomplete_or_blocked_response(reason: str) -> None:
    with pytest.raises(InvalidAIOutputError):
        validate("A partial answer", finish_reason=reason)


@pytest.mark.parametrize(
    "text",
    ["   ", "<think>Internal reasoning</think>Answer"],
)
def test_rejects_empty_or_reasoning_output(text: str) -> None:
    with pytest.raises(InvalidAIOutputError):
        validate(text)


def test_retries_invalid_output_once() -> None:
    attempts = 0

    async def generate() -> str:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            raise OutputParserException("Missing priority")

        return "valid"

    result = asyncio.run(
        run_with_output_retry(
            operation="test_output",
            call=generate,
        )
    )

    assert result == "valid"
    assert attempts == 2


def test_stops_after_second_invalid_output() -> None:
    attempts = 0

    async def generate() -> str:
        nonlocal attempts
        attempts += 1
        raise InvalidAIOutputError("Invalid citation")

    with pytest.raises(InvalidAIOutputError):
        asyncio.run(
            run_with_output_retry(
                operation="test_output",
                call=generate,
            )
        )

    assert attempts == 2


def test_does_not_retry_unrelated_application_error() -> None:
    attempts = 0

    async def generate() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("Application failure")

    with pytest.raises(RuntimeError, match="Application failure"):
        asyncio.run(
            run_with_output_retry(
                operation="test_output",
                call=generate,
            )
        )

    assert attempts == 1


@pytest.mark.parametrize("stage", ["analysis", "recommendation"])
def test_ai_stages_retry_unsupported_citation(
    monkeypatch,
    stage: str,
) -> None:
    attempts = 0

    async def fake_model(prompt_value):
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return AIMessage(content="A fabricated record [TOOL 3].")

        return AIMessage(
            content="Request transaction details before proceeding.",
            response_metadata={"finish_reason": "stop"},
        )

    module = analyzer_module if stage == "analysis" else recommender_module

    monkeypatch.setattr(
        module,
        "get_chat_model",
        lambda: RunnableLambda(fake_model),
    )

    if stage == "analysis":
        result = asyncio.run(
            analyzer_module.analyze_incident(
                title="Payment issue",
                description="Insufficient payment details.",
                category="payment",
                priority="medium",
                evidence=[],
            )
        )
    else:
        result = asyncio.run(
            recommender_module.recommend_incident_action(
                title="Payment issue",
                description="Insufficient payment details.",
                category="payment",
                priority="medium",
                analysis="The available information is insufficient.",
                evidence=[],
            )
        )

    assert result == "Request transaction details before proceeding."
    assert attempts == 2
