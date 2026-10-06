import uuid
from types import SimpleNamespace

import ops_pilot.workflows.incident.checkpointing as checkpointing_module
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryRetrievalResult,
)


def test_checkpoint_database_url_removes_sqlalchemy_driver(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        checkpointing_module,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=("postgresql+psycopg://user:password@example.com/database?sslmode=require")
        ),
    )

    result = checkpointing_module.get_checkpoint_database_url()

    assert result == ("postgresql://user:password@example.com/database?sslmode=require")


def test_checkpoint_serializer_round_trips_incident_memory() -> None:
    serializer = checkpointing_module.get_checkpoint_serializer()

    memory = IncidentMemoryRetrievalResult(
        memory_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        subject_customer_id=None,
        category="payment",
        summary="Previous duplicate charge.",
        resolution="Duplicate charge was refunded.",
        vector_score=0.91,
    )

    encoded = serializer.dumps_typed(
        memory,
    )

    decoded = serializer.loads_typed(
        encoded,
    )

    assert isinstance(
        decoded,
        IncidentMemoryRetrievalResult,
    )

    assert decoded == memory
