import asyncio
from unittest.mock import patch

from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.workflows.incident.nodes import propose_action_node


def test_unverified_payment_cannot_create_action_proposal() -> None:
    state = {
        "title": "Possible duplicate payment",
        "description": "Two charges with unverified payment identity.",
        "category": IncidentCategory.PAYMENT,
        "priority": IncidentPriority.HIGH,
        "evidence": [],
        "analysis": "Insufficient proof of a duplicate.",
        "recommended_action": "Request manual verification.",
        "tool_results": [],
        "duplicate_payment_candidate": None,
    }

    with patch(
        "ops_pilot.workflows.incident.nodes.has_required_operational_evidence",
        return_value=True,
    ):
        result = asyncio.run(propose_action_node(state))  # type: ignore[arg-type]

    assert result["proposed_action"] is None
    assert result["approval_required"] is False
