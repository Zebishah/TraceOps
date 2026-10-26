"""Tests for durable approval outcome verification."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.approval_resume_processor as processor
import ops_pilot.services.approval_resume_reconciliation as reconciliation
from ops_pilot.models.approval import ApprovalStatus
from ops_pilot.services.approval_resume_recovery import ClaimedResumeJob


def make_job() -> ClaimedResumeJob:
    return ClaimedResumeJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        approval_request_id=uuid.uuid4(),
        lease_token=uuid.uuid4(),
        attempts=1,
    )


def make_graph(job, *, verified=True):
    class FakeGraph:
        async def aget_state(self, config):
            return SimpleNamespace(
                next=(),
                tasks=(),
                values={
                    "organization_id": job.organization_id,
                    "incident_id": job.incident_id,
                    "approval_request_id": job.approval_request_id,
                    "refund_verified": verified,
                },
            )

    return FakeGraph()


def test_executed_approval_requires_persisted_refund(
    monkeypatch,
):
    job = make_job()

    verify_ledger = AsyncMock(return_value=False)

    monkeypatch.setattr(
        reconciliation,
        "verify_persisted_refund",
        verify_ledger,
    )

    with pytest.raises(
        RuntimeError,
        match="Refund ledger verification failed",
    ):
        asyncio.run(
            processor.verify_resume_outcome(
                graph=make_graph(job),
                config={
                    "configurable": {
                        "thread_id": "test-executed",
                    }
                },
                job=job,
                approval_status=ApprovalStatus.EXECUTED,
                source_external_id="TXN-123",
            )
        )

    verify_ledger.assert_awaited_once_with(
        organization_id=job.organization_id,
        incident_id=job.incident_id,
        approval_request_id=job.approval_request_id,
        source_external_id="TXN-123",
    )


def test_executed_approval_passes_when_ledger_matches(
    monkeypatch,
):
    job = make_job()

    verify_ledger = AsyncMock(return_value=True)

    monkeypatch.setattr(
        reconciliation,
        "verify_persisted_refund",
        verify_ledger,
    )

    asyncio.run(
        processor.verify_resume_outcome(
            graph=make_graph(job),
            config={
                "configurable": {
                    "thread_id": "test-valid",
                }
            },
            job=job,
            approval_status=ApprovalStatus.EXECUTED,
            source_external_id="TXN-123",
        )
    )

    verify_ledger.assert_awaited_once()


def test_missing_source_id_is_rejected():
    job = make_job()

    with pytest.raises(
        RuntimeError,
        match="missing its source transaction ID",
    ):
        asyncio.run(
            processor.verify_resume_outcome(
                graph=make_graph(job),
                config={
                    "configurable": {
                        "thread_id": "test-missing",
                    }
                },
                job=job,
                approval_status=ApprovalStatus.EXECUTED,
                source_external_id=None,
            )
        )


def test_mismatched_checkpoint_cannot_verify(
    monkeypatch,
):
    job = make_job()
    graph = make_graph(job)

    original = graph.aget_state

    async def wrong_snapshot(config):
        snapshot = await original(config)
        snapshot.values["organization_id"] = uuid.uuid4()
        return snapshot

    graph.aget_state = wrong_snapshot

    verify_ledger = AsyncMock(return_value=True)

    monkeypatch.setattr(
        reconciliation,
        "verify_persisted_refund",
        verify_ledger,
    )

    with pytest.raises(RuntimeError, match="mismatch"):
        asyncio.run(
            processor.verify_resume_outcome(
                graph=graph,
                config={
                    "configurable": {
                        "thread_id": "test-wrong-tenant",
                    }
                },
                job=job,
                approval_status=ApprovalStatus.EXECUTED,
                source_external_id="TXN-123",
            )
        )

    verify_ledger.assert_not_awaited()


def test_rejected_approval_never_checks_refund(
    monkeypatch,
):
    job = make_job()

    class RejectedGraph:
        async def aget_state(self, config):
            return SimpleNamespace(
                next=(),
                tasks=(),
                values={
                    "organization_id": job.organization_id,
                    "incident_id": job.incident_id,
                    "approval_request_id": job.approval_request_id,
                    "approval_decision": {
                        "approved": False,
                    },
                },
            )

    verify_ledger = AsyncMock()

    monkeypatch.setattr(
        reconciliation,
        "verify_persisted_refund",
        verify_ledger,
    )

    asyncio.run(
        processor.verify_resume_outcome(
            graph=RejectedGraph(),
            config={
                "configurable": {
                    "thread_id": "test-rejected",
                }
            },
            job=job,
            approval_status=ApprovalStatus.REJECTED,
            source_external_id=None,
        )
    )

    verify_ledger.assert_not_awaited()
