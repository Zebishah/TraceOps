import uuid
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

import ops_pilot.workflows.incident.nodes as nodes
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.tools.schemas import OperationalToolName, ToolCallRequest
from ops_pilot.workflows.incident.state import IncidentInvestigationState


@pytest.mark.asyncio
@pytest.mark.parametrize("required_call_pending", [True, False])
async def test_payment_planning_does_not_use_optional_llm(
    monkeypatch: pytest.MonkeyPatch,
    required_call_pending: bool,
) -> None:
    required_call = ToolCallRequest(
        call_id="required-orders",
        tool_name=OperationalToolName.LIST_CUSTOMER_ORDERS,
        arguments={"limit": 10},
    )

    planner = Mock(
        return_value=required_call if required_call_pending else None,
    )
    optional_selector = AsyncMock()

    monkeypatch.setattr(nodes, "required_operational_tool", planner)
    monkeypatch.setattr(nodes, "select_incident_tool", optional_selector)

    state = cast(
        IncidentInvestigationState,
        {
            "subject_customer_id": uuid.uuid4(),
            "title": "Possible duplicate payment",
            "description": "Inspect current payment records.",
            "category": IncidentCategory.PAYMENT,
            "priority": IncidentPriority.HIGH,
            "evidence": [],
            "tool_results": [],
            "tool_round": 0,
        },
    )

    result = await nodes.select_operational_tool_node(state)

    if required_call_pending:
        assert result["pending_tool_call"] is required_call
    else:
        assert result["pending_tool_call"] is None

    assert result["needs_more_information"] is False
    planner.assert_called_once()
    optional_selector.assert_not_awaited()
