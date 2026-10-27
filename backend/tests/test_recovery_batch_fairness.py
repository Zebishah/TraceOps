"""Regression tests for bounded and incremental recovery sweeps."""

import uuid
from unittest.mock import AsyncMock

import pytest

from ops_pilot.services import approval_resume_processor as processor
from ops_pilot.services import approval_resume_reconciliation as reconciliation
from ops_pilot.services.approval_resume_recovery import ClaimedResumeJob


def job() -> ClaimedResumeJob:
    return ClaimedResumeJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        approval_request_id=uuid.uuid4(),
        lease_token=uuid.uuid4(),
        attempts=1,
    )


@pytest.mark.anyio
async def test_sweep_claims_one_at_a_time_and_processes_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = [job(), job(), job()]

    claim = AsyncMock(
        side_effect=[[item] for item in jobs],
    )
    process = AsyncMock()
    renew = AsyncMock(return_value=True)
    complete = AsyncMock(return_value=True)

    monkeypatch.setattr(processor, "claim_resume_jobs", claim)
    monkeypatch.setattr(processor, "process_claimed_resume_job", process)
    monkeypatch.setattr(processor, "renew_resume_job_lease", renew)
    monkeypatch.setattr(processor, "complete_resume_job", complete)

    async def heartbeat(*, job: ClaimedResumeJob, stop, owner, **kwargs) -> None:
        await stop.wait()

    monkeypatch.setattr(
        processor,
        "keep_resume_job_lease_alive",
        heartbeat,
    )

    result = await processor.run_approval_resume_sweep()

    assert result.claimed == 3
    assert result.completed == 3
    assert result.failed == 0

    assert claim.await_count == 3
    assert process.await_count == 3
    assert complete.await_count == 3

    for call in claim.await_args_list:
        assert call.kwargs == {"limit": 1}


@pytest.mark.anyio
async def test_sweep_stops_after_first_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = AsyncMock(return_value=[job()])

    monkeypatch.setattr(processor, "claim_resume_jobs", claim)
    monkeypatch.setattr(
        processor,
        "process_claimed_resume_job",
        AsyncMock(side_effect=RuntimeError("Uncertain outcome")),
    )

    failed = AsyncMock(return_value=True)

    monkeypatch.setattr(processor, "fail_resume_job", failed)

    async def heartbeat(*, job: ClaimedResumeJob, stop, owner, **kwargs) -> None:
        await stop.wait()

    monkeypatch.setattr(
        processor,
        "keep_resume_job_lease_alive",
        heartbeat,
    )

    result = await processor.run_approval_resume_sweep()

    assert result.claimed == 1
    assert result.completed == 0
    assert result.failed == 1

    assert claim.await_count == 1
    assert failed.await_args.kwargs["terminal"] is True


def test_reconciliation_cooldown_is_positive() -> None:
    assert reconciliation.RECONCILIATION_RECHECK_SECONDS > 0


def test_sweep_batch_limit_is_bounded() -> None:
    assert 1 < processor.RECOVERY_SWEEP_BATCH_SIZE <= 5
    assert processor.RECOVERY_SWEEP_BUDGET_SECONDS > 0


@pytest.mark.anyio
async def test_recovery_sweep_stops_after_bounded_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sweep must not process more than its configured batch size."""

    jobs = [job() for _ in range(10)]

    next_jobs = iter([[item] for item in jobs])

    claimed_ids: list[uuid.UUID] = []
    processed_ids: list[uuid.UUID] = []

    async def claim(*, limit: int):
        assert limit == 1
        result = next(next_jobs, [])
        claimed_ids.extend(item.id for item in result)
        return result

    async def process(current: ClaimedResumeJob):
        processed_ids.append(current.id)

    async def heartbeat(
        *,
        job: ClaimedResumeJob,
        stop,
        owner,
        **kwargs,
    ) -> None:
        await stop.wait()

    monkeypatch.setattr(
        processor,
        "claim_resume_jobs",
        claim,
    )
    monkeypatch.setattr(
        processor,
        "process_claimed_resume_job",
        process,
    )
    monkeypatch.setattr(
        processor,
        "renew_resume_job_lease",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        processor,
        "complete_resume_job",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        processor,
        "keep_resume_job_lease_alive",
        heartbeat,
    )

    result = await processor.run_approval_resume_sweep()

    assert result.claimed == processor.RECOVERY_SWEEP_BATCH_SIZE
    assert result.completed == processor.RECOVERY_SWEEP_BATCH_SIZE
    assert result.failed == 0

    assert len(claimed_ids) == processor.RECOVERY_SWEEP_BATCH_SIZE
    assert len(set(claimed_ids)) == len(claimed_ids)

    assert processed_ids == claimed_ids

    # No additional job should be claimed beyond the batch.
    assert jobs[processor.RECOVERY_SWEEP_BATCH_SIZE].id not in claimed_ids
