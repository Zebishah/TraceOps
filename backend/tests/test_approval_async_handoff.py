import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import ops_pilot.services.approval_workflow as workflow
from ops_pilot.models.approval import ApprovalStatus
from ops_pilot.schemas.approvals import ApprovalDecisionRequest


def test_approval_decision_uses_durable_recording(
    monkeypatch,
) -> None:
    """The API must enqueue, not execute LangGraph inline."""

    approval = SimpleNamespace(
        id=uuid.uuid4(),
        status=ApprovalStatus.APPROVED,
    )
    recorded = AsyncMock(return_value=approval)

    monkeypatch.setattr(
        workflow,
        "record_approval_decision",
        recorded,
    )

    session = AsyncMock()
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()
    payload = ApprovalDecisionRequest(
        approved=True,
        comment="Approved by reviewer",
    )

    result = asyncio.run(
        workflow.decide_and_resume_approval(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            approval_request_id=approval_id,
            decided_by_user_id=reviewer_id,
            payload=payload,
        )
    )

    assert result is approval

    recorded.assert_awaited_once_with(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_id,
        decided_by_user_id=reviewer_id,
        payload=payload,
    )


def test_rejected_decision_uses_same_durable_path(
    monkeypatch,
) -> None:
    approval = SimpleNamespace(
        id=uuid.uuid4(),
        status=ApprovalStatus.REJECTED,
    )
    recorded = AsyncMock(return_value=approval)

    monkeypatch.setattr(
        workflow,
        "record_approval_decision",
        recorded,
    )

    result = asyncio.run(
        workflow.decide_and_resume_approval(
            session=AsyncMock(),
            organization_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            approval_request_id=uuid.uuid4(),
            decided_by_user_id=uuid.uuid4(),
            payload=ApprovalDecisionRequest(
                approved=False,
                comment="Not authorized",
            ),
        )
    )

    assert result.status == ApprovalStatus.REJECTED
    recorded.assert_awaited_once()
