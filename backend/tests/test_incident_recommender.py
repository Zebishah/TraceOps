import asyncio
import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import ops_pilot.ai.incident_recommender as recommender_module
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.schemas.retrieval import RetrievalResult


def test_recommend_incident_action_uses_analysis_and_evidence(
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
            content=(
                "Verify both transaction IDs before refunding the duplicate payment [SOURCE 1]."
            )
        )

    monkeypatch.setattr(
        recommender_module,
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
        recommender_module.recommend_incident_action(
            title="Customer charged twice",
            description="Customer reports two charges.",
            category=IncidentCategory.PAYMENT,
            priority=IncidentPriority.HIGH,
            analysis=("The evidence supports a possible duplicate payment [SOURCE 1]."),
            evidence=evidence,
        )
    )

    assert result == (
        "Verify both transaction IDs before refunding the duplicate payment [SOURCE 1]."
    )

    assert "Do not execute tools" in captured["system"]
    assert "Customer charged twice" in captured["human"]
    assert "possible duplicate payment" in captured["human"]
    assert "[SOURCE 1]" in captured["human"]


def test_recommend_incident_action_rejects_empty_response(
    monkeypatch,
) -> None:
    async def fake_model(prompt_value):
        return AIMessage(
            content="   ",
        )

    monkeypatch.setattr(
        recommender_module,
        "get_chat_model",
        lambda: RunnableLambda(fake_model),
    )

    with pytest.raises(
        RuntimeError,
        match="Incident recommender returned an empty recommendation",
    ):
        asyncio.run(
            recommender_module.recommend_incident_action(
                title="Test incident",
                description="Test description",
                category=IncidentCategory.OTHER,
                priority=IncidentPriority.LOW,
                analysis="No clear cause was established.",
                evidence=[],
            )
        )
