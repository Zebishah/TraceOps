import asyncio
import uuid
from types import SimpleNamespace

import ops_pilot.services.incident_memory_retrieval as retrieval_module


def test_build_incident_memory_query() -> None:
    query = retrieval_module.build_incident_memory_query(
        title="Customer charged twice",
        description="Two charges appeared for one order.",
        category="payment",
    )

    assert query == (
        "Category: payment\n"
        "Incident title: Customer charged twice\n"
        "Incident description: Two charges appeared for one order."
    )


def test_retrieve_similar_incident_memories(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    current_incident_id = uuid.uuid4()

    previous_memory_id = uuid.uuid4()
    previous_incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    async def fake_embed_query(
        query: str,
    ) -> list[float]:
        assert "Customer charged twice" in query

        return [0.1] * 1024

    async def fake_ensure_memory_collection() -> None:
        return None

    class FakeClient:
        async def query_points(
            self,
            *,
            collection_name,
            query,
            query_filter,
            limit,
            with_payload,
            with_vectors,
        ):
            assert collection_name == ("ops_pilot_incident_memories_v1")

            assert len(query) == 1024
            assert limit == 3
            assert with_payload is True
            assert with_vectors is False

            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id=str(previous_memory_id),
                        score=0.93,
                        payload={
                            "organization_id": str(
                                organization_id,
                            ),
                            "incident_id": str(
                                previous_incident_id,
                            ),
                            "subject_customer_id": str(
                                customer_id,
                            ),
                            "category": "payment",
                            "summary": ("Customer had two successful charges for one order."),
                            "resolution": ("The duplicate charge was refunded."),
                        },
                    )
                ]
            )

    monkeypatch.setattr(
        retrieval_module,
        "embed_query",
        fake_embed_query,
    )

    monkeypatch.setattr(
        retrieval_module,
        "ensure_memory_collection",
        fake_ensure_memory_collection,
    )

    monkeypatch.setattr(
        retrieval_module,
        "get_qdrant_client",
        lambda: FakeClient(),
    )

    monkeypatch.setattr(
        retrieval_module,
        "get_settings",
        lambda: SimpleNamespace(
            qdrant_memory_collection_name=("ops_pilot_incident_memories_v1"),
        ),
    )

    result = asyncio.run(
        retrieval_module.retrieve_similar_incident_memories(
            organization_id=organization_id,
            current_incident_id=current_incident_id,
            title="Customer charged twice",
            description=("Two charges appeared for one order."),
            category="payment",
        )
    )

    assert len(result) == 1

    memory = result[0]

    assert memory.memory_id == previous_memory_id
    assert memory.incident_id == previous_incident_id
    assert memory.subject_customer_id == customer_id
    assert memory.category == "payment"
    assert memory.vector_score == 0.93
    assert memory.resolution == ("The duplicate charge was refunded.")
