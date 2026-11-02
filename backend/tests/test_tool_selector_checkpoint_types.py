from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import ops_pilot.ai.incident_tool_selector as selector
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("category", "priority"),
    [
        (IncidentCategory.PAYMENT, IncidentPriority.HIGH),
        ("payment", "high"),
    ],
)
async def test_tool_selector_accepts_enum_and_checkpoint_strings(
    monkeypatch: pytest.MonkeyPatch,
    category: IncidentCategory | str,
    priority: IncidentPriority | str,
) -> None:
    model = Mock()
    model.bind_tools.return_value = RunnableLambda(
        lambda _prompt: AIMessage(content="No additional tool needed.")
    )
    monkeypatch.setattr(selector, "get_chat_model", lambda: model)

    result = await selector.select_incident_tool(
        title="Possible duplicate payment",
        description="Inspect the available evidence.",
        category=category,
        priority=priority,
        evidence=[],
        tool_results=[],
    )

    assert result is None
    model.bind_tools.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("category", "priority"),
    [
        ("invalid-category", "high"),
        ("payment", "invalid-priority"),
    ],
)
async def test_invalid_classification_fails_before_model_access(
    monkeypatch: pytest.MonkeyPatch,
    category: str,
    priority: str,
) -> None:
    get_model = Mock()
    monkeypatch.setattr(selector, "get_chat_model", get_model)

    with pytest.raises(ValueError):
        await selector.select_incident_tool(
            title="Invalid checkpoint",
            description="Classification must be validated.",
            category=category,
            priority=priority,
            evidence=[],
            tool_results=[],
        )

    get_model.assert_not_called()
