"""Regression tests for quarantined approval verification."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import ops_pilot.services.approval_resume_reconciliation as recovery
from ops_pilot.models.approval import ApprovalStatus


def make_records(
    *,
    status: ApprovalStatus = ApprovalStatus.EXECUTED,
):
    org_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    job_id = uuid.uuid4()

    approval = SimpleNamespace(
        id=approval_id,
        organization_id=org_id,
        incident_id=incident_id,
        workflow_thread_id=f"thread-{approval_id}",
        action_payload={"external_transaction_id": "TXN-123"},
        status=status,
    )

    job = SimpleNamespace(
        id=job_id,
        organization_id=org_id,
        incident_id=incident_id,
        approval_request_id=approval_id,
        lease_token=None,
        attempts=5,
    )

    return approval, job


def configure_reconciliation(
    monkeypatch,
    approval,
    job,
):
    session = AsyncMock()

    result = Mock()
    result.one_or_none.return_value = (approval, job)
    session.execute.return_value = result

    class SessionFactory:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    class CheckpointerFactory:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        recovery,
        "async_session_factory",
        SessionFactory,
    )
    monkeypatch.setattr(
        recovery,
        "open_incident_checkpointer",
        CheckpointerFactory,
    )
    monkeypatch.setattr(
        recovery,
        "build_incident_investigation_graph",
        lambda **kwargs: object(),
    )

    return session


def test_quarantined_job_verifies_correct_identity(
    monkeypatch,
):
    approval, job = make_records()

    configure_reconciliation(
        monkeypatch,
        approval,
        job,
    )

    verifier = AsyncMock(return_value=None)

    monkeypatch.setattr(
        recovery,
        "verify_resume_outcome",
        verifier,
    )

    verified = asyncio.run(recovery.verify_quarantined_job(job_id=job.id))

    assert verified is True
    verifier.assert_awaited_once()

    kwargs = verifier.await_args.kwargs
    identity = kwargs["job"]

    assert identity.organization_id == job.organization_id
    assert identity.incident_id == job.incident_id
    assert identity.approval_request_id == job.approval_request_id
    assert kwargs["source_external_id"] == "TXN-123"


def test_unverified_checkpoint_stays_quarantined(
    monkeypatch,
):
    approval, job = make_records()

    configure_reconciliation(
        monkeypatch,
        approval,
        job,
    )

    verifier = AsyncMock(side_effect=RuntimeError("Approval checkpoint organization_id mismatch"))

    monkeypatch.setattr(
        recovery,
        "verify_resume_outcome",
        verifier,
    )

    verified = asyncio.run(recovery.verify_quarantined_job(job_id=job.id))

    assert verified is False


@pytest.mark.parametrize(
    "status",
    [
        ApprovalStatus.APPROVED,
        ApprovalStatus.PENDING,
    ],
)
def test_nonterminal_approval_cannot_reconcile(
    monkeypatch,
    status,
):
    approval, job = make_records(status=status)

    configure_reconciliation(
        monkeypatch,
        approval,
        job,
    )

    verifier = AsyncMock()

    monkeypatch.setattr(
        recovery,
        "verify_resume_outcome",
        verifier,
    )

    verified = asyncio.run(recovery.verify_quarantined_job(job_id=job.id))

    assert verified is False
    verifier.assert_not_awaited()
