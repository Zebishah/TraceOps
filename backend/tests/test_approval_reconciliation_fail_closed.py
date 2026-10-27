"""Regression tests for fail-closed quarantined reconciliation."""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.approval_resume_reconciliation as reconciliation


def test_verified_quarantined_job_is_not_automatically_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid.uuid4()

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [job_id]

    session = AsyncMock()
    session.execute.side_effect = [
        FakeResult(),
        AsyncMock(),
    ]

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

    verifier = AsyncMock(return_value=True)

    monkeypatch.setattr(
        reconciliation,
        "verify_quarantined_job",
        verifier,
    )

    result = asyncio.run(reconciliation.reconcile_quarantined_jobs())

    assert result.inspected == 1
    assert result.completed == 0
    assert result.unresolved == 1

    verifier.assert_awaited_once_with(job_id=job_id)

    # Selection plus cooldown update.
    assert session.execute.await_count == 2
    session.commit.assert_awaited_once()

    # The generated UPDATE must not transition the
    # recovery job to COMPLETED.
    update_statement = session.execute.await_args_list[1].args[0]

    from sqlalchemy.dialects import postgresql

    compiled = update_statement.compile(dialect=postgresql.dialect())

    sql = str(compiled).lower()

    assert "update approval_resume_jobs" in sql
    assert "next_attempt_at" in sql
    assert "status=" not in sql.split("set", 1)[-1].split("where", 1)[0]
