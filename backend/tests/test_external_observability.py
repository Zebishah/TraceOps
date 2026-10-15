import logging
from typing import Protocol, cast

import pytest

from ops_pilot.integrations.observability import (
    observe_external_call,
)


class ExternalLogRecord(Protocol):
    provider: str
    operation: str
    duration_ms: float


@pytest.mark.anyio
async def test_external_call_logs_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_call() -> str:
        return "ok"

    with caplog.at_level(logging.INFO):
        result = await observe_external_call(
            provider="mistral",
            operation="embeddings",
            call=fake_call,
        )

    assert result == "ok"

    success_record = cast(
        ExternalLogRecord,
        next(record for record in caplog.records if record.message == "external_call_succeeded"),
    )

    assert success_record.provider == "mistral"
    assert success_record.operation == "embeddings"
    assert success_record.duration_ms >= 0


@pytest.mark.anyio
async def test_external_call_logs_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_call() -> None:
        raise RuntimeError("provider failed")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(
            RuntimeError,
            match="provider failed",
        ):
            await observe_external_call(
                provider="voyage",
                operation="rerank",
                call=fake_call,
            )

    assert any(record.message == "external_call_failed" for record in caplog.records)
