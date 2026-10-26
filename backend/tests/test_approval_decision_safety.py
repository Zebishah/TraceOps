import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.models.approval import ApprovalStatus
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.schemas.approvals import ApprovalDecisionRequest
from ops_pilot.services.approvals import record_approval_decision
from ops_pilot.services.incident_resolution import (
    IncidentResolutionConflict,
)


def make_session(incident, approval):
    session = AsyncMock()

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    approval_result = Mock()
    approval_result.scalar_one_or_none.return_value = approval

    session.execute.side_effect = [
        incident_result,
        approval_result,
    ]

    return session


def execute_decision(session, approved=False):
    return asyncio.run(
        record_approval_decision(
            session=session,
            organization_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            approval_request_id=uuid.uuid4(),
            decided_by_user_id=uuid.uuid4(),
            payload=ApprovalDecisionRequest(
                approved=approved,
                comment="Reviewed payment evidence.",
            ),
        )
    )


def test_rejection_cannot_reopen_resolved_incident():
    incident = SimpleNamespace(status=IncidentStatus.RESOLVED)
    approval = SimpleNamespace(status=ApprovalStatus.PENDING)

    session = make_session(incident, approval)

    with pytest.raises(
        IncidentResolutionConflict,
        match="resolved incident",
    ):
        execute_decision(session)

    assert incident.status == IncidentStatus.RESOLVED
    assert approval.status == ApprovalStatus.PENDING
    session.commit.assert_not_awaited()


def test_rejection_returns_incident_to_investigating():
    incident = SimpleNamespace(status=IncidentStatus.AWAITING_APPROVAL)

    approval = SimpleNamespace(
        status=ApprovalStatus.PENDING,
        decided_by_user_id=None,
        decision_comment=None,
        decided_at=None,
    )

    session = make_session(incident, approval)

    result = execute_decision(session)

    assert result.status == ApprovalStatus.REJECTED
    assert incident.status == IncidentStatus.INVESTIGATING
    assert approval.decided_at is not None
    session.commit.assert_awaited_once()


def test_approved_decision_preserves_awaiting_approval():
    incident = SimpleNamespace(status=IncidentStatus.AWAITING_APPROVAL)

    approval = SimpleNamespace(
        status=ApprovalStatus.PENDING,
        decided_by_user_id=None,
        decision_comment=None,
        decided_at=None,
    )

    session = make_session(incident, approval)

    result = execute_decision(session, approved=True)

    assert result.status == ApprovalStatus.APPROVED
    assert incident.status == IncidentStatus.AWAITING_APPROVAL
    session.commit.assert_awaited_once()
