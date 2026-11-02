import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.services.approval_resume_processor as processor
import ops_pilot.services.approval_resume_recovery as recovery


@pytest.mark.asyncio
async def test_scoped_claim_filters_job_and_organization(
    monkeypatch,
) -> None:
    job_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    statements = []

    @asynccontextmanager
    async def transaction():
        yield

    class FakeSession:
        def begin(self):
            return transaction()

        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    @asynccontextmanager
    async def sessions():
        yield FakeSession()

    monkeypatch.setattr(
        recovery,
        "async_session_factory",
        sessions,
    )

    jobs = await recovery.claim_resume_jobs(
        limit=1,
        job_id=job_id,
        organization_id=organization_id,
    )

    assert jobs == []
    assert len(statements) == 1

    compiled = statements[0].compile()
    sql = str(compiled)

    assert "approval_resume_jobs.id =" in sql
    assert "approval_resume_jobs.organization_id =" in sql
    assert "FOR UPDATE" in sql
    assert job_id in compiled.params.values()
    assert organization_id in compiled.params.values()


@pytest.mark.asyncio
async def test_scoped_sweep_passes_exact_identity(
    monkeypatch,
) -> None:
    job_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    claim = AsyncMock(return_value=[])

    monkeypatch.setattr(processor, "claim_resume_jobs", claim)

    result = await processor.run_approval_resume_sweep(
        job_id=job_id,
        organization_id=organization_id,
    )

    claim.assert_awaited_once_with(
        limit=1,
        job_id=job_id,
        organization_id=organization_id,
    )
    assert result.claimed == 0
    assert result.completed == 0
    assert result.failed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    ["claim", "sweep"],
)
async def test_partial_scope_is_rejected_before_database_access(
    monkeypatch,
    target: str,
) -> None:
    sessions = AsyncMock()
    claim = AsyncMock()

    monkeypatch.setattr(
        recovery,
        "async_session_factory",
        sessions,
    )
    monkeypatch.setattr(
        processor,
        "claim_resume_jobs",
        claim,
    )

    with pytest.raises(
        ValueError,
        match="must be supplied together",
    ):
        if target == "claim":
            await recovery.claim_resume_jobs(
                job_id=uuid.uuid4(),
            )
        else:
            await processor.run_approval_resume_sweep(
                job_id=uuid.uuid4(),
            )

    sessions.assert_not_called()
    claim.assert_not_awaited()
