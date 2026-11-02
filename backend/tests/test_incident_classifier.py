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


def test_classifier_retries_malformed_output(monkeypatch) -> None:
    from langchain_core.exceptions import OutputParserException

    attempts = 0

    async def fake_ainvoke(self, payload):
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            raise OutputParserException("Missing priority")

        return IncidentClassification(
            category=IncidentCategory.PAYMENT,
            priority=IncidentPriority.HIGH,
            confidence=0.95,
        )

    monkeypatch.setattr(FakeChain, "ainvoke", fake_ainvoke)
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

    assert result.priority == IncidentPriority.HIGH
    assert attempts == 2


def test_classifier_stops_after_two_malformed_outputs(monkeypatch) -> None:
    import pytest
    from langchain_core.exceptions import OutputParserException

    attempts = 0

    async def fake_ainvoke(self, payload):
        nonlocal attempts
        attempts += 1
        raise OutputParserException("Missing priority")

    monkeypatch.setattr(FakeChain, "ainvoke", fake_ainvoke)
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

    with pytest.raises(OutputParserException):
        asyncio.run(
            classifier_module.classify_incident(
                title="Customer charged twice",
                description="Customer was charged twice for one order.",
            )
        )

    assert attempts == 2
