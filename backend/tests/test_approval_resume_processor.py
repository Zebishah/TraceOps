import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.approval_resume_processor as processor
from ops_pilot.models.approval import ApprovalStatus
from ops_pilot.services.approval_resume_recovery import (
    ClaimedResumeJob,
)


def make_job() -> ClaimedResumeJob:
    return ClaimedResumeJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        approval_request_id=uuid.uuid4(),
        lease_token=uuid.uuid4(),
        attempts=1,
    )


def test_successful_job_completes(monkeypatch):
    job = make_job()

    process = AsyncMock()
    complete = AsyncMock(return_value=True)
    fail = AsyncMock()

    monkeypatch.setattr(
        processor,
        "claim_resume_jobs",
        AsyncMock(return_value=[job]),
    )
    monkeypatch.setattr(
        processor,
        "process_claimed_resume_job",
        process,
    )
    monkeypatch.setattr(
        processor,
        "complete_resume_job",
        complete,
    )
    monkeypatch.setattr(
        processor,
        "fail_resume_job",
        fail,
    )
    monkeypatch.setattr(
        processor,
        "renew_resume_job_lease",
        AsyncMock(return_value=True),
    )
    result = asyncio.run(processor.run_approval_resume_sweep())

    assert result.claimed == 1
    assert result.completed == 1
    assert result.failed == 0

    process.assert_awaited_once_with(job)
    complete.assert_awaited_once_with(job=job)
    fail.assert_not_awaited()


def test_failed_job_schedules_retry(monkeypatch):
    job = make_job()

    monkeypatch.setattr(
        processor,
        "claim_resume_jobs",
        AsyncMock(return_value=[job]),
    )
    monkeypatch.setattr(
        processor,
        "process_claimed_resume_job",
        AsyncMock(side_effect=RuntimeError("Provider failed")),
    )

    complete = AsyncMock()
    fail = AsyncMock(return_value=True)

    monkeypatch.setattr(
        processor,
        "complete_resume_job",
        complete,
    )
    monkeypatch.setattr(
        processor,
        "fail_resume_job",
        fail,
    )

    result = asyncio.run(processor.run_approval_resume_sweep())

    assert result.claimed == 1
    assert result.completed == 0
    assert result.failed == 1

    complete.assert_not_awaited()
    fail.assert_awaited_once()


def test_terminal_executed_requires_verified_refund():
    class FakeGraph:
        async def aget_state(self, config):
            return type(
                "Snapshot",
                (),
                {
                    "next": (),
                    "tasks": (),
                    "values": {"refund_verified": False},
                },
            )()

    with pytest.raises(
        RuntimeError,
        match="without verification",
    ):
        asyncio.run(
            processor.verify_terminal_checkpoint(
                graph=FakeGraph(),
                config={"configurable": {"thread_id": "test"}},
                approval_status=ApprovalStatus.EXECUTED,
            )
        )


def test_terminal_rejection_is_accepted():
    class FakeGraph:
        async def aget_state(self, config):
            return type(
                "Snapshot",
                (),
                {
                    "next": (),
                    "tasks": (),
                    "values": {
                        "approval_decision": {
                            "approved": False,
                        }
                    },
                },
            )()

    asyncio.run(
        processor.verify_terminal_checkpoint(
            graph=FakeGraph(),
            config={"configurable": {"thread_id": "test"}},
            approval_status=ApprovalStatus.REJECTED,
        )
    )


def test_nonterminal_checkpoint_is_rejected():
    class FakeGraph:
        async def aget_state(self, config):
            return type(
                "Snapshot",
                (),
                {
                    "next": ("execute_approved_action",),
                    "tasks": (),
                    "values": {},
                },
            )()

    with pytest.raises(
        RuntimeError,
        match="terminal checkpoint",
    ):
        asyncio.run(
            processor.verify_terminal_checkpoint(
                graph=FakeGraph(),
                config={"configurable": {"thread_id": "test"}},
                approval_status=ApprovalStatus.EXECUTED,
            )
        )


def test_heartbeat_renews_active_lease(monkeypatch):
    job = make_job()

    renewed = asyncio.Event()
    stop = asyncio.Event()

    async def fake_renew(*, job):
        renewed.set()
        return True

    monkeypatch.setattr(
        processor,
        "renew_resume_job_lease",
        fake_renew,
    )

    async def scenario():
        async def owner_task():
            await renewed.wait()
            stop.set()

        owner = asyncio.create_task(owner_task())

        await processor.keep_resume_job_lease_alive(
            job=job,
            stop=stop,
            owner=owner,
            interval_seconds=0.001,
        )

        await owner

    asyncio.run(scenario())

    assert renewed.is_set()


def test_heartbeat_cancels_owner_on_lost_lease(monkeypatch):
    job = make_job()

    monkeypatch.setattr(
        processor,
        "renew_resume_job_lease",
        AsyncMock(return_value=False),
    )

    async def scenario():
        stop = asyncio.Event()

        async def owner_task():
            await asyncio.sleep(10)

        owner = asyncio.create_task(owner_task())

        heartbeat = asyncio.create_task(
            processor.keep_resume_job_lease_alive(
                job=job,
                stop=stop,
                owner=owner,
                interval_seconds=0.001,
            )
        )

        await heartbeat

        assert owner.cancelling() > 0

        with pytest.raises(asyncio.CancelledError):
            await owner

    asyncio.run(scenario())
