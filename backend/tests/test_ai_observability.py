import logging
from typing import Protocol, cast

import pytest

from ops_pilot.ai.observability import (
    observe_llm_call,
)


class ObservedLogRecord(Protocol):
    message: str
    provider: str
    operation: str
    model: str
    duration_ms: float


@pytest.mark.anyio
async def test_observe_llm_call_returns_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_call() -> str:
        return "ok"

    with caplog.at_level(logging.INFO):
        result = await observe_llm_call(
            operation="test_operation",
            call=fake_call,
        )

    assert result == "ok"

    messages = [record.message for record in caplog.records]

    assert "llm_call_started" in messages
    assert "llm_call_succeeded" in messages


@pytest.mark.anyio
async def test_observe_llm_call_logs_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_call() -> str:
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(
            RuntimeError,
            match="boom",
        ):
            await observe_llm_call(
                operation="test_operation",
                call=fake_call,
            )

    assert any(record.message == "llm_call_failed" for record in caplog.records)


@pytest.mark.anyio
async def test_llm_log_contains_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_call() -> str:
        return "ok"

    with caplog.at_level(logging.INFO):
        await observe_llm_call(
            operation="incident_classification",
            call=fake_call,
        )

    success_record = cast(
        ObservedLogRecord,
        next(record for record in caplog.records if record.message == "llm_call_succeeded"),
    )

    assert success_record.provider == "groq"
    assert success_record.operation == "incident_classification"
    assert success_record.model
    assert success_record.duration_ms >= 0
