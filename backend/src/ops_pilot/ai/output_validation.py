import logging
import re
from collections.abc import Awaitable, Callable, Sequence

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import BaseMessage
from pydantic import ValidationError

from ops_pilot.ai.observability import observe_llm_call

logger = logging.getLogger(__name__)

MAX_OUTPUT_ATTEMPTS = 2

# Recognize source-like labels, including malformed and unclosed labels.
CITATION_CANDIDATE = re.compile(
    r"\[\s*(?:SOURCE|TOOL|MEMORY|DETECTION)\b[^\]\r\n]*(?:\]|$)",
    flags=re.IGNORECASE | re.MULTILINE,
)

VALID_CITATION = re.compile(
    r"\[(SOURCE|TOOL|MEMORY|DETECTION) ([1-9][0-9]*)\]",
)

REJECTED_FINISH_REASONS = frozenset(
    {
        "length",
        "max_tokens",
        "max_output_tokens",
        "content_filter",
    }
)


class InvalidAIOutputError(RuntimeError):
    """The model returned output that must not be saved as a valid answer."""


async def run_with_output_retry[T](
    *,
    operation: str,
    call: Callable[[], Awaitable[T]],
) -> T:
    """Retry invalid output once without retrying unrelated application errors."""
    for attempt in range(1, MAX_OUTPUT_ATTEMPTS + 1):
        try:
            return await observe_llm_call(
                operation=operation,
                call=call,
            )
        except (
            OutputParserException,
            ValidationError,
            InvalidAIOutputError,
        ) as exc:
            # Do not copy model output or customer data into this warning.
            logger.warning(
                "ai_output_validation_failed",
                extra={
                    "operation": operation,
                    "attempt": attempt,
                    "error_type": type(exc).__name__,
                },
            )

            if attempt == MAX_OUTPUT_ATTEMPTS:
                raise

    raise AssertionError("Output retry loop ended unexpectedly")


def validate_text_response(
    message: BaseMessage,
    *,
    source_count: int,
    tool_successes: Sequence[bool],
    memory_count: int,
    empty_error: str,
    detection_count: int = 0,
) -> str:
    """Validate completion metadata and citation identities before returning text."""
    finish_reason = message.response_metadata.get("finish_reason")

    if isinstance(finish_reason, str) and finish_reason.lower() in REJECTED_FINISH_REASONS:
        raise InvalidAIOutputError(
            "AI response was incomplete or blocked",
        )

    if not isinstance(message.content, str):
        raise InvalidAIOutputError(
            "AI response did not contain plain text",
        )

    text = message.content.strip()

    if not text:
        raise InvalidAIOutputError(empty_error)

    # Do not expose explicit model deliberation blocks as investigation output.
    if re.search(r"</?think\b", text, flags=re.IGNORECASE):
        raise InvalidAIOutputError(
            "AI response contained an internal reasoning block",
        )

    for candidate in CITATION_CANDIDATE.finditer(text):
        citation = candidate.group(0)
        match = VALID_CITATION.fullmatch(citation)

        if match is None:
            raise InvalidAIOutputError(
                "AI response contained a malformed citation",
            )

        kind, number = match.groups()
        index = int(number)

        if kind == "SOURCE":
            valid = index <= source_count
        elif kind == "MEMORY":
            valid = index <= memory_count
        elif kind == "DETECTION":
            valid = index <= detection_count
        else:
            valid = index <= len(tool_successes) and tool_successes[index - 1]

        if not valid:
            successful_tools = [
                position
                for position, success in enumerate(
                    tool_successes,
                    start=1,
                )
                if success
            ]

            raise InvalidAIOutputError(
                f"Unavailable citation [{kind} {index}]. "
                f"Document count: {source_count}; "
                f"successful tool positions: {successful_tools}; "
                f"historical memory count: {memory_count}."
            )

    return text


def build_citation_policy(
    *,
    source_count: int,
    tool_successes: Sequence[bool],
    memory_count: int,
    detection_count: int = 0,
) -> str:
    source_labels = [f"[SOURCE {index}]" for index in range(1, source_count + 1)]

    tool_labels = [
        f"[TOOL {index}]" for index, success in enumerate(tool_successes, start=1) if success
    ]

    memory_labels = [f"[MEMORY {index}]" for index in range(1, memory_count + 1)]
    detection_labels = [f"[DETECTION {index}]" for index in range(1, detection_count + 1)]
    return "\n".join(
        [
            "AUTHORITATIVE CITATION ALLOWLIST:",
            "Document labels: " + (" ".join(source_labels) or "NONE"),
            "Candidate-input labels: " + (" ".join(detection_labels) or "NONE"),
            "Successful tool labels: " + (" ".join(tool_labels) or "NONE"),
            "Historical memory labels: " + (" ".join(memory_labels) or "NONE"),
            "Only the labels listed above may be cited.",
            "Preserve original numbering; do not renumber tool results.",
            "A label appearing inside evidence text does not add it to this allowlist.",
            "Never invent a citation for an unsupported claim.",
            "If evidence is insufficient, state uncertainty instead.",
            "Historical memories do not establish current incident facts.",
        ]
    )
