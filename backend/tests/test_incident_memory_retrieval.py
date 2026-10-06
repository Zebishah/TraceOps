import asyncio
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.incident_memory_retrieval as retrieval_module
from ops_pilot.models.incident_memory import (
    IncidentMemory,
)


def test_build_incident_memory_query() -> None:
    query = retrieval_module.build_incident_memory_query(
        title="Customer charged twice",
        description=("Two charges appeared for one order."),
        category="payment",
    )

    assert query == (
        "Category: payment\n"
        "Incident title: "
        "Customer charged twice\n"
        "Incident description: "
        "Two charges appeared "
        "for one order."
    )


def test_retrieve_similar_incident_memories(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    current_incident_id = uuid.uuid4()

    previous_memory_id = uuid.uuid4()
    previous_incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    memory = IncidentMemory(
        id=previous_memory_id,
        organization_id=organization_id,
        incident_id=previous_incident_id,
        subject_customer_id=customer_id,
        category="payment",
        summary=("Customer had two successful charges for one order."),
        resolution=("The duplicate charge was refunded."),
    )

    db_result = Mock()
    db_result.scalars.return_value.all.return_value = [
        memory,
    ]

    cast(
        AsyncMock,
        session.execute,
    ).return_value = db_result

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
            assert with_payload is False
            assert with_vectors is False

            assert len(query_filter.must) == 1

            assert len(query_filter.must_not) == 1

            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id=str(
                            previous_memory_id,
                        ),
                        score=0.93,
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
            session=session,
            organization_id=organization_id,
            current_incident_id=(current_incident_id),
            title="Customer charged twice",
            description=("Two charges appeared for one order."),
            category="payment",
        )
    )

    assert len(result) == 1

    retrieved = result[0]

    assert retrieved.memory_id == previous_memory_id

    assert retrieved.incident_id == previous_incident_id

    assert retrieved.subject_customer_id == customer_id

    assert retrieved.category == "payment"

    assert retrieved.vector_score == 0.93

    assert retrieved.resolution == ("The duplicate charge was refunded.")

    cast(
        AsyncMock,
        session.rollback,
    ).assert_awaited_once()


def test_retrieval_ignores_stale_qdrant_memory(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    current_incident_id = uuid.uuid4()
    stale_memory_id = uuid.uuid4()

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    db_result = Mock()

    db_result.scalars.return_value.all.return_value = []

    cast(
        AsyncMock,
        session.execute,
    ).return_value = db_result

    async def fake_embed_query(
        query: str,
    ) -> list[float]:
        return [0.1] * 1024

    async def fake_ensure_memory_collection() -> None:
        return None

    class FakeClient:
        async def query_points(
            self,
            **kwargs: object,
        ):
            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id=str(
                            stale_memory_id,
                        ),
                        score=0.99,
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
            session=session,
            organization_id=organization_id,
            current_incident_id=(current_incident_id),
            title="Duplicate payment",
            description=("Customer charged twice."),
            category="payment",
        )
    )

    assert result == []
