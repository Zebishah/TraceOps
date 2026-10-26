import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import ops_pilot.services.approval_resume_recovery as recovery
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJobStatus,
)


def test_expired_processing_job_is_quarantined(monkeypatch):
    job = SimpleNamespace(
        id=uuid.uuid4(),
        status=ApprovalResumeJobStatus.PROCESSING.value,
        attempts=2,
        lease_token=uuid.uuid4(),
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        last_error=None,
    )

    result = Mock()
    result.scalars.return_value.all.return_value = [job]

    session = AsyncMock()

    # SQLAlchemy session.begin() returns an async context manager,
    # not a coroutine.
    session.begin = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=None)

    session.execute.return_value = result

    class FakeFactory:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        recovery,
        "async_session_factory",
        FakeFactory,
    )

    count = asyncio.run(recovery.quarantine_expired_resume_jobs())

    assert count == 1
    assert job.status == ApprovalResumeJobStatus.FAILED.value
    assert job.attempts == recovery.MAX_ATTEMPTS
    assert job.lease_token is None
    assert job.lease_expires_at is None
    assert "outcome uncertain" in job.last_error
    assert session.execute.await_count == 1
    session.begin.assert_called_once()


def test_quarantine_with_no_expired_jobs(monkeypatch):
    result = Mock()
    result.scalars.return_value.all.return_value = []

    session = AsyncMock()

    session.begin = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=None)

    session.execute.return_value = result

    class FakeFactory:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        recovery,
        "async_session_factory",
        FakeFactory,
    )

    count = asyncio.run(recovery.quarantine_expired_resume_jobs())

    assert count == 0
    session.execute.assert_awaited_once()
    session.begin.assert_called_once()
