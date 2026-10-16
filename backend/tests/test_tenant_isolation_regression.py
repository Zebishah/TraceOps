import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.services.incident_memory_retrieval as memory_retrieval
import ops_pilot.services.retrieval as retrieval_service
from ops_pilot.core.exceptions import IncidentNotFoundError
from ops_pilot.services.incidents import get_incident
from ops_pilot.services.operational_data import (
    get_payment_transaction,
    list_order_payments,
)


@pytest.mark.anyio
async def test_incident_lookup_is_scoped_by_organization() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    result = Mock()
    result.scalar_one_or_none.return_value = None

    cast(
        AsyncMock,
        session.execute,
    ).return_value = result

    with pytest.raises(IncidentNotFoundError):
        await get_incident(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )

    execute_mock = cast(AsyncMock, session.execute)
    await_args = execute_mock.await_args
    assert await_args is not None
    statement = await_args.args[0]

    compiled = statement.compile()

    values = set(compiled.params.values())

    assert organization_id in values
    assert incident_id in values


@pytest.mark.anyio
async def test_payment_transaction_lookup_is_tenant_scoped() -> None:
    organization_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    result = Mock()
    result.scalar_one_or_none.return_value = None

    cast(
        AsyncMock,
        session.execute,
    ).return_value = result

    transaction = await get_payment_transaction(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        external_transaction_id="TXN-SECURITY-1",
    )

    assert transaction is None

    execute_mock = cast(AsyncMock, session.execute)
    assert execute_mock.await_args is not None
    statement = execute_mock.await_args.args[0]

    compiled = statement.compile()

    values = set(compiled.params.values())

    assert organization_id in values
    assert customer_id in values
    assert "TXN-SECURITY-1" in values


@pytest.mark.anyio
async def test_order_payment_listing_is_tenant_scoped() -> None:
    organization_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    result = Mock()
    result.scalars.return_value.all.return_value = []

    cast(
        AsyncMock,
        session.execute,
    ).return_value = result

    payments = await list_order_payments(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        external_order_id="ORD-SECURITY-1",
    )

    assert payments == []

    execute_mock = cast(AsyncMock, session.execute)
    assert execute_mock.await_args is not None
    statement = execute_mock.await_args.args[0]

    compiled = statement.compile()

    values = set(compiled.params.values())

    assert organization_id in values
    assert customer_id in values
    assert "ORD-SECURITY-1" in values


@pytest.mark.anyio
async def test_document_vector_search_filters_by_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()

    async def fake_embed_query(
        query: str,
    ) -> list[float]:
        return [0.1] * 1024

    captured_filter = None

    class FakeClient:
        async def query_points(
            self,
            **kwargs: object,
        ):
            nonlocal captured_filter

            captured_filter = kwargs["query_filter"]

            return SimpleNamespace(points=[])

    monkeypatch.setattr(
        retrieval_service,
        "embed_query",
        fake_embed_query,
    )

    monkeypatch.setattr(
        retrieval_service,
        "get_qdrant_client",
        lambda: FakeClient(),
    )

    monkeypatch.setattr(
        retrieval_service,
        "get_settings",
        lambda: SimpleNamespace(
            qdrant_collection_name=("document_chunks"),
            retrieval_candidate_limit=12,
        ),
    )

    result = await retrieval_service.retrieve_document_chunks(
        organization_id=organization_id,
        query="payment policy",
    )

    assert result == []
    assert captured_filter is not None

    must = captured_filter.must

    assert len(must) == 1

    condition = must[0]

    assert condition.key == "organization_id"

    assert condition.match.value == str(organization_id)


@pytest.mark.anyio
async def test_incident_memory_search_filters_qdrant_by_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

    async def fake_embed_query(
        query: str,
    ) -> list[float]:
        return [0.1] * 1024

    async def fake_ensure_memory_collection() -> None:
        return None

    captured_filter = None

    class FakeClient:
        async def query_points(
            self,
            **kwargs: object,
        ):
            nonlocal captured_filter

            captured_filter = kwargs["query_filter"]

            return SimpleNamespace(points=[])

    monkeypatch.setattr(
        memory_retrieval,
        "embed_query",
        fake_embed_query,
    )

    monkeypatch.setattr(
        memory_retrieval,
        "ensure_memory_collection",
        fake_ensure_memory_collection,
    )

    monkeypatch.setattr(
        memory_retrieval,
        "get_qdrant_client",
        lambda: FakeClient(),
    )

    monkeypatch.setattr(
        memory_retrieval,
        "get_settings",
        lambda: SimpleNamespace(
            qdrant_memory_collection_name=("incident_memories"),
        ),
    )

    result = await memory_retrieval.retrieve_similar_incident_memories(
        session=session,
        organization_id=organization_id,
        current_incident_id=incident_id,
        title="Duplicate payment",
        description="Customer charged twice",
        category="payment",
    )

    assert result == []
    assert captured_filter is not None

    must = captured_filter.must
    must_not = captured_filter.must_not

    assert len(must) == 1
    assert len(must_not) == 1

    assert must[0].key == "organization_id"

    assert must[0].match.value == str(organization_id)

    assert must_not[0].key == "incident_id"

    assert must_not[0].match.value == str(incident_id)


@pytest.mark.anyio
async def test_incident_memory_db_lookup_is_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    memory_id = uuid.uuid4()

    session = cast(
        AsyncSession,
        AsyncMock(spec=AsyncSession),
    )

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
                        id=str(memory_id),
                        score=0.9,
                    )
                ]
            )

    result = Mock()
    result.scalars.return_value.all.return_value = []

    cast(
        AsyncMock,
        session.execute,
    ).return_value = result

    monkeypatch.setattr(
        memory_retrieval,
        "embed_query",
        fake_embed_query,
    )

    monkeypatch.setattr(
        memory_retrieval,
        "ensure_memory_collection",
        fake_ensure_memory_collection,
    )

    monkeypatch.setattr(
        memory_retrieval,
        "get_qdrant_client",
        lambda: FakeClient(),
    )

    monkeypatch.setattr(
        memory_retrieval,
        "get_settings",
        lambda: SimpleNamespace(
            qdrant_memory_collection_name=("incident_memories"),
        ),
    )

    result_values = await memory_retrieval.retrieve_similar_incident_memories(
        session=session,
        organization_id=organization_id,
        current_incident_id=incident_id,
        title="Duplicate payment",
        description="Customer charged twice",
        category="payment",
    )

    assert result_values == []

    execute_mock = cast(
        AsyncMock,
        session.execute,
    )
    await_call = execute_mock.await_args
    assert await_call is not None
    statement = await_call.args[0]

    compiled = statement.compile()

    values = list(compiled.params.values())

    assert organization_id in values
    assert incident_id in values
