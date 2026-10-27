"""Ensure safe preflight failures retry and uncertain outcomes quarantine."""

import uuid
from unittest.mock import AsyncMock

import pytest

from ops_pilot.services import approval_resume_processor as processor
from ops_pilot.services.approval_resume_recovery import ClaimedResumeJob


def example_job() -> ClaimedResumeJob:
    return ClaimedResumeJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        approval_request_id=uuid.uuid4(),
        lease_token=uuid.uuid4(),
        attempts=1,
    )


@pytest.mark.anyio
async def test_transient_preflight_failure_allows_bounded_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = example_job()

    monkeypatch.setattr(
        processor,
        "claim_resume_jobs",
        AsyncMock(return_value=[job]),
    )

    monkeypatch.setattr(
        processor,
        "process_claimed_resume_job",
        AsyncMock(
            side_effect=processor.ResumePreflightReadError(
                "Temporary database failure loading approval"
            )
        ),
    )

    failed = AsyncMock(return_value=True)

    monkeypatch.setattr(
        processor,
        "fail_resume_job",
        failed,
    )

    async def idle_heartbeat(**kwargs: object) -> None:
        await kwargs["stop"].wait()  # type: ignore[union-attr]

    monkeypatch.setattr(
        processor,
        "keep_resume_job_lease_alive",
        idle_heartbeat,
    )

    result = await processor.run_approval_resume_sweep()

    assert result.claimed == 1
    assert result.completed == 0
    assert result.failed == 1

    failed.assert_awaited_once()

    assert failed.await_args.kwargs["job"] == job
    assert failed.await_args.kwargs["terminal"] is False


@pytest.mark.anyio
async def test_uncertain_financial_failure_is_quarantined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = example_job()

    monkeypatch.setattr(
        processor,
        "claim_resume_jobs",
        AsyncMock(return_value=[job]),
    )

    monkeypatch.setattr(
        processor,
        "process_claimed_resume_job",
        AsyncMock(side_effect=RuntimeError("Outcome uncertain after workflow execution")),
    )

    failed = AsyncMock(return_value=True)

    monkeypatch.setattr(
        processor,
        "fail_resume_job",
        failed,
    )

    async def idle_heartbeat(**kwargs: object) -> None:
        await kwargs["stop"].wait()  # type: ignore[union-attr]

    monkeypatch.setattr(
        processor,
        "keep_resume_job_lease_alive",
        idle_heartbeat,
    )

    result = await processor.run_approval_resume_sweep()

    assert result.failed == 1

    failed.assert_awaited_once()

    assert failed.await_args.kwargs["job"] == job
    assert failed.await_args.kwargs["terminal"] is True
