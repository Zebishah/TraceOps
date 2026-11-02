from typing import cast
from unittest.mock import Mock

import pytest

import ops_pilot.workflows.incident.nodes as nodes
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.workflows.incident.state import IncidentInvestigationState


@pytest.mark.parametrize(
    "category",
    [
        IncidentCategory.PAYMENT,
        "payment",
    ],
)
def test_duplicate_detection_accepts_checkpoint_category(
    monkeypatch: pytest.MonkeyPatch,
    category: IncidentCategory | str,
) -> None:
    detector = Mock(return_value=None)
    monkeypatch.setattr(
        nodes,
        "detect_duplicate_payment_candidate",
        detector,
    )

    # Deliberately simulate persisted data despite the TypedDict annotation.
    state = cast(
        IncidentInvestigationState,
        {"category": category, "tool_results": []},
    )

    result = nodes.detect_duplicate_payment_node(state)

    assert result == {"duplicate_payment_candidate": None}
    detector.assert_called_once_with(tool_results=[])


def test_non_payment_checkpoint_skips_duplicate_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = Mock()
    monkeypatch.setattr(
        nodes,
        "detect_duplicate_payment_candidate",
        detector,
    )

    state = cast(
        IncidentInvestigationState,
        {"category": "access", "tool_results": []},
    )

    result = nodes.detect_duplicate_payment_node(state)

    assert result == {"duplicate_payment_candidate": None}
    detector.assert_not_called()


def test_invalid_checkpoint_category_is_rejected() -> None:
    state = cast(
        IncidentInvestigationState,
        {"category": "invalid-category", "tool_results": []},
    )

    with pytest.raises(ValueError):
        nodes.detect_duplicate_payment_node(state)
