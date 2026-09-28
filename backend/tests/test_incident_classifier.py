import asyncio

import ops_pilot.ai.incident_classifier as classifier_module
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
    IncidentClassification,
)


class FakeChain:
    async def ainvoke(self, payload):
        assert payload == {
            "title": "Customer charged twice",
            "description": "Customer was charged twice for one order.",
        }

        return IncidentClassification(
            category=IncidentCategory.PAYMENT,
            priority=IncidentPriority.HIGH,
            confidence=0.98,
        )


class FakePrompt:
    def __or__(self, other):
        return FakeChain()


class FakeModel:
    def with_structured_output(
        self,
        schema,
        *,
        method,
        strict,
    ):
        assert schema is IncidentClassification
        assert method == "json_schema"
        assert strict is True

        return object()


def test_classify_incident_returns_structured_result(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        classifier_module,
        "get_chat_model",
        lambda: FakeModel(),
    )

    monkeypatch.setattr(
        classifier_module,
        "CLASSIFICATION_PROMPT",
        FakePrompt(),
    )

    result = asyncio.run(
        classifier_module.classify_incident(
            title="Customer charged twice",
            description="Customer was charged twice for one order.",
        )
    )

    assert result.category == IncidentCategory.PAYMENT
    assert result.priority == IncidentPriority.HIGH
    assert result.confidence == 0.98
