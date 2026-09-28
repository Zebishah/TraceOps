from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import SecretStr

import ops_pilot.ai.llm as llm_module


def test_get_chat_model_uses_configured_model(
    monkeypatch,
) -> None:
    llm_module.get_chat_model.cache_clear()

    monkeypatch.setattr(
        llm_module,
        "get_settings",
        lambda: SimpleNamespace(
            generation_model="qwen/qwen3.8-27b",
            groq_api_key="test-key",
        ),
    )

    fake_model = Mock()

    chat_groq = Mock(
        return_value=fake_model,
    )

    monkeypatch.setattr(
        llm_module,
        "ChatGroq",
        chat_groq,
    )

    result = llm_module.get_chat_model()

    assert result is fake_model

    chat_groq.assert_called_once_with(
        model="qwen/qwen3.8-27b",
        api_key=SecretStr("test-key"),
        temperature=0,
        max_retries=2,
        timeout=30.0,
    )

    llm_module.get_chat_model.cache_clear()
