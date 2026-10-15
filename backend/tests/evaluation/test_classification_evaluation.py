from unittest.mock import AsyncMock

import pytest

from ops_pilot.evaluation import classification
from ops_pilot.models.incident import (
    IncidentPriority,
)
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
    IncidentClassification,
)


@pytest.mark.anyio
async def test_classification_evaluation_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_classify_incident(
        *,
        title: str,
        description: str,
    ) -> IncidentClassification:
        del description

        mapping = {
            "Customer charged twice": (
                IncidentCategory.PAYMENT,
                IncidentPriority.HIGH,
            ),
            "User cannot sign in": (
                IncidentCategory.ACCESS,
                IncidentPriority.MEDIUM,
            ),
            "Payment webhook failing": (
                IncidentCategory.INTEGRATION,
                IncidentPriority.HIGH,
            ),
            "Application unavailable": (
                IncidentCategory.SYSTEM,
                IncidentPriority.CRITICAL,
            ),
            "Possible account compromise": (
                IncidentCategory.SECURITY,
                IncidentPriority.HIGH,
            ),
            "Customer profile data incorrect": (
                IncidentCategory.DATA,
                IncidentPriority.MEDIUM,
            ),
            "Profile name cannot be updated": (
                IncidentCategory.ACCOUNT,
                IncidentPriority.LOW,
            ),
            "Billing problem": (
                IncidentCategory.PAYMENT,
                IncidentPriority.HIGH,
            ),
        }
        category, priority = mapping[title]

        return IncidentClassification(
            category=category,
            priority=priority,
            confidence=0.95,
        )

    mock = AsyncMock(
        side_effect=fake_classify_incident,
    )

    monkeypatch.setattr(
        classification,
        "classify_incident",
        mock,
    )

    result = await classification.evaluate_incident_classification()

    assert result.total_cases == 8
    assert result.passed_cases == 8, result.model_dump_json(
        indent=2,
    )
    assert result.failed_cases == 0
    assert result.pass_rate == 1.0
    assert mock.await_count == 8
