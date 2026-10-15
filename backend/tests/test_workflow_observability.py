import logging
from typing import Protocol, cast

import pytest

from ops_pilot.workflows.observability import (
    observe_workflow_step,
)


class WorkflowLogRecord(Protocol):
    node: str
    incident_id: str
    workflow_thread_id: str
    duration_ms: float


@pytest.mark.anyio
async def test_workflow_step_logs_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_call() -> str:
        return "done"

    with caplog.at_level(logging.INFO):
        result = await observe_workflow_step(
            node="analyze_incident",
            incident_id="incident-123",
            workflow_thread_id="thread-123",
            call=fake_call,
        )

    assert result == "done"

    success_record = cast(
        WorkflowLogRecord,
        next(record for record in caplog.records if record.message == "workflow_step_succeeded"),
    )

    assert success_record.node == "analyze_incident"
    assert success_record.incident_id == "incident-123"
    assert success_record.workflow_thread_id == "thread-123"
    assert success_record.duration_ms >= 0


@pytest.mark.anyio
async def test_workflow_step_logs_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_call() -> None:
        raise RuntimeError("workflow failed")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(
            RuntimeError,
            match="workflow failed",
        ):
            await observe_workflow_step(
                node="retrieve_evidence",
                incident_id="incident-123",
                workflow_thread_id="thread-123",
                call=fake_call,
            )

    assert any(record.message == "workflow_step_failed" for record in caplog.records)
