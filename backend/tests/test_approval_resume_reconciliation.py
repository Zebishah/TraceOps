import asyncio
import uuid
from unittest.mock import AsyncMock

import ops_pilot.services.approval_resume_reconciliation as reconciliation


def test_unverified_job_remains_unresolved(monkeypatch):
    job_id = uuid.uuid4()

    monkeypatch.setattr(
        reconciliation,
        "verify_quarantined_job",
        AsyncMock(return_value=False),
    )

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [job_id]

    class FakeSession:
        async def execute(self, statement):
            return FakeResult()

        async def rollback(self):
            pass

    class FakeFactory:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        reconciliation,
        "async_session_factory",
        FakeFactory,
    )

    result = asyncio.run(reconciliation.reconcile_quarantined_jobs())

    assert result.inspected == 1
    assert result.completed == 0
    assert result.unresolved == 1


def test_invalid_reconciliation_limit():
    try:
        asyncio.run(reconciliation.reconcile_quarantined_jobs(limit=0))
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_missing_source_charge_cannot_verify_refund(
    monkeypatch,
) -> None:
    from unittest.mock import AsyncMock

    session = AsyncMock()
    session.scalar.return_value = None

    class FakeFactory:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        reconciliation,
        "async_session_factory",
        FakeFactory,
    )

    result = asyncio.run(
        reconciliation.verify_persisted_refund(
            organization_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            approval_request_id=uuid.uuid4(),
            source_external_id="MISSING-CHARGE",
        )
    )

    assert result is False
