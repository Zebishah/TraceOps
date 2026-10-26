import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ops_pilot.models.approval import ApprovalActionType
from ops_pilot.models.incident import IncidentStatus
from ops_pilot.schemas.incident_actions import IncidentActionProposal
from ops_pilot.services.approvals import (
    create_or_get_pending_approval,
)
from ops_pilot.services.incident_resolution import (
    IncidentResolutionConflict,
)


def test_resolved_incident_cannot_create_approval() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    incident = SimpleNamespace(
        id=incident_id,
        organization_id=organization_id,
        status=IncidentStatus.RESOLVED,
    )

    db_result = Mock()
    db_result.scalar_one_or_none.return_value = incident

    session = AsyncMock()
    session.execute.return_value = db_result

    proposal = IncidentActionProposal(
        requires_approval=True,
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        external_transaction_id="TXN-123",
        amount=Decimal("100.00"),
        currency="USD",
        reason="Verified duplicate charge.",
    )

    with pytest.raises(
        IncidentResolutionConflict,
        match="resolved incident",
    ):
        asyncio.run(
            create_or_get_pending_approval(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                workflow_thread_id="test-thread",
                proposal=proposal,
            )
        )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()

    assert incident.status == IncidentStatus.RESOLVED
    assert session.execute.await_count == 1
