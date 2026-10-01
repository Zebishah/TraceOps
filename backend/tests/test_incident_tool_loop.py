import asyncio
import uuid

import ops_pilot.workflows.incident.nodes as nodes_module
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory


def test_tool_selector_requests_customer_information_when_missing() -> None:
    result = asyncio.run(
        nodes_module.select_operational_tool_node(
            {
                "organization_id": uuid.uuid4(),
                "incident_id": uuid.uuid4(),
                "title": "Customer charged twice",
                "description": "Why was I charged twice?",
                "category": IncidentCategory.PAYMENT,
                "priority": IncidentPriority.HIGH,
                "evidence": [],
            }
        )
    )

    assert result["pending_tool_call"] is None
    assert result["needs_more_information"] is True
    assert result["clarification_question"] is not None
