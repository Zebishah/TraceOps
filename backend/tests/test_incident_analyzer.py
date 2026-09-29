import asyncio
import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import ops_pilot.ai.incident_analyzer as analyzer_module
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.schemas.retrieval import RetrievalResult


def test_analyze_incident_uses_grounded_evidence(
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    async def fake_model(prompt_value):
        messages = prompt_value.to_messages()

        captured["system"] = str(
            messages[0].content,
        )

        captured["human"] = str(
            messages[-1].content,
        )

        return AIMessage(
            content=("The incident is consistent with a duplicate payment [SOURCE 1].")
        )

    monkeypatch.setattr(
        analyzer_module,
        "get_chat_model",
        lambda: RunnableLambda(fake_model),
    )

    evidence = [
        RetrievalResult(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=0,
            page_number=2,
            text=("Duplicate payments must be verified before a refund is issued."),
            source_filename="payment-policy.pdf",
            vector_score=0.91,
            reranker_score=0.97,
        )
    ]

    result = asyncio.run(
        analyzer_module.analyze_incident(
            title="Customer charged twice",
            description=("Customer reports two charges for one order."),
            category=IncidentCategory.PAYMENT,
            priority=IncidentPriority.HIGH,
            evidence=evidence,
        )
    )

    assert result == ("The incident is consistent with a duplicate payment [SOURCE 1].")

    assert "Do not use outside knowledge" in captured["system"]

    assert "Customer charged twice" in captured["human"]

    assert "[SOURCE 1]" in captured["human"]

    assert "payment-policy.pdf" in captured["human"]


def test_analyze_incident_rejects_empty_response(
    monkeypatch,
) -> None:
    async def fake_model(prompt_value):
        return AIMessage(
            content="   ",
        )

    monkeypatch.setattr(
        analyzer_module,
        "get_chat_model",
        lambda: RunnableLambda(fake_model),
    )

    with pytest.raises(
        RuntimeError,
        match="Incident analyzer returned an empty analysis",
    ):
        asyncio.run(
            analyzer_module.analyze_incident(
                title="Test incident",
                description="Test description",
                category=IncidentCategory.OTHER,
                priority=IncidentPriority.LOW,
                evidence=[],
            )
        )
