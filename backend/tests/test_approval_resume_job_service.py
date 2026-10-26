import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
)
from ops_pilot.services.approvals import (
    ensure_approval_resume_job,
)


def make_approval():
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
    )


def test_creates_job_when_missing():
    session = AsyncMock()
    session.add = Mock()
    session.scalar.return_value = None

    approval = make_approval()

    asyncio.run(
        ensure_approval_resume_job(
            session=session,
            approval=approval,
        )
    )

    session.add.assert_called_once()

    job = session.add.call_args.args[0]

    assert isinstance(job, ApprovalResumeJob)
    assert job.approval_request_id == approval.id
    assert job.organization_id == approval.organization_id
    assert job.incident_id == approval.incident_id
    assert job.status == "pending"

    session.commit.assert_not_awaited()


def test_does_not_duplicate_existing_job():
    session = AsyncMock()
    session.add = Mock()
    session.scalar.return_value = uuid.uuid4()

    asyncio.run(
        ensure_approval_resume_job(
            session=session,
            approval=make_approval(),
        )
    )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()
