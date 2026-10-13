import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import Client

from ops_pilot.mcp.server import mcp
from ops_pilot.models.incident import (
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.models.membership import MembershipRole
from ops_pilot.schemas.mcp_auth import MCPAuthenticatedContext
from ops_pilot.schemas.mcp_incidents import (
    MCPIncidentDetail,
    MCPIncidentSummary,
)
from ops_pilot.schemas.project_knowledge import (
    ProjectKnowledgeResult,
)

ORGANIZATION_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
INCIDENT_ID = uuid.uuid4()


class FakeSessionContext:
    def __init__(self) -> None:
        self.session = AsyncMock()

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None


@pytest.mark.anyio
async def test_mcp_health_tool() -> None:
    async with Client(
        mcp,
        raise_exceptions=True,
    ) as client:
        tools = await client.list_tools()

        tool_names = {tool.name for tool in tools.tools}

        assert "ops_pilot_health" in tool_names
        assert "search_project_knowledge" in tool_names
        assert "list_open_incidents" in tool_names
        assert "search_incidents" in tool_names
        assert "get_incident" in tool_names
        assert "get_customer" in tool_names
        assert "list_customer_orders" in tool_names
        assert "get_order" in tool_names
        assert "list_order_payments" in tool_names
        assert "get_payment_transaction" in tool_names
        assert "search_incident_memory" in tool_names
        result = await client.call_tool(
            "ops_pilot_health",
            {},
        )

        assert result.structured_content == {
            "status": "ok",
            "service": "ops-pilot-mcp",
        }


@pytest.mark.anyio
async def test_search_project_knowledge_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_project_knowledge(
        *,
        query: str,
        limit: int = 5,
    ) -> list[ProjectKnowledgeResult]:
        assert query == "How does HITL work?"
        assert limit == 3

        return [
            ProjectKnowledgeResult(
                source="hitl-and-refunds.md",
                section="Human Approval",
                text=("OpsPilot pauses sensitive actions until a human approves them."),
                vector_score=0.81,
                reranker_score=0.96,
            )
        ]

    monkeypatch.setattr(
        "ops_pilot.mcp.server.search_project_knowledge_service",
        fake_search_project_knowledge,
    )

    async with Client(
        mcp,
        raise_exceptions=True,
    ) as client:
        result = await client.call_tool(
            "search_project_knowledge",
            {
                "query": "How does HITL work?",
                "limit": 3,
            },
        )

        assert result.structured_content == {
            "query": "How does HITL work?",
            "results": [
                {
                    "source": "hitl-and-refunds.md",
                    "section": "Human Approval",
                    "text": ("OpsPilot pauses sensitive actions until a human approves them."),
                    "vector_score": 0.81,
                    "reranker_score": 0.96,
                }
            ],
        }


@pytest.mark.anyio
async def test_operational_tool_requires_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ops_pilot.mcp.server.get_access_token",
        lambda: None,
    )

    async with Client(
        mcp,
        raise_exceptions=True,
    ) as client:
        result = await client.call_tool(
            "list_open_incidents",
            {
                "organization_id": str(ORGANIZATION_ID),
            },
        )

    assert result.is_error is True
    assert result.structured_content is None


@pytest.mark.anyio
async def test_list_open_incidents_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)

    fake_access_token = SimpleNamespace(
        token="valid-token",
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.get_access_token",
        lambda: fake_access_token,
    )

    fake_authenticate = AsyncMock(
        return_value=MCPAuthenticatedContext(
            user_id=USER_ID,
            organization_id=ORGANIZATION_ID,
            role=MembershipRole.OPERATOR,
        )
    )

    fake_list = AsyncMock(
        return_value=[
            MCPIncidentSummary(
                id=INCIDENT_ID,
                title="Customer charged twice",
                status=IncidentStatus.INVESTIGATING,
                category="payment",
                priority=IncidentPriority.HIGH,
                subject_customer_id=None,
                created_at=now,
                updated_at=now,
            )
        ]
    )

    fake_session_context = FakeSessionContext()

    monkeypatch.setattr(
        "ops_pilot.mcp.server.authenticate_mcp_access",
        fake_authenticate,
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.list_open_incidents_service",
        fake_list,
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.async_session_factory",
        lambda: fake_session_context,
    )

    async with Client(
        mcp,
        raise_exceptions=True,
    ) as client:
        result = await client.call_tool(
            "list_open_incidents",
            {
                "organization_id": str(ORGANIZATION_ID),
                "limit": 10,
            },
        )

    fake_authenticate.assert_awaited_once_with(
        session=fake_session_context.session,
        access_token="valid-token",
        organization_id=ORGANIZATION_ID,
    )

    fake_list.assert_awaited_once_with(
        session=fake_session_context.session,
        organization_id=ORGANIZATION_ID,
        limit=10,
    )

    assert result.structured_content is not None

    assert len(result.structured_content["incidents"]) == 1

    assert result.structured_content["incidents"][0]["title"] == "Customer charged twice"


@pytest.mark.anyio
async def test_search_incidents_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_access_token = SimpleNamespace(
        token="valid-token",
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.get_access_token",
        lambda: fake_access_token,
    )

    fake_authenticate = AsyncMock(
        return_value=MCPAuthenticatedContext(
            user_id=USER_ID,
            organization_id=ORGANIZATION_ID,
            role=MembershipRole.VIEWER,
        )
    )

    fake_search = AsyncMock(
        return_value=[],
    )

    fake_session_context = FakeSessionContext()

    monkeypatch.setattr(
        "ops_pilot.mcp.server.authenticate_mcp_access",
        fake_authenticate,
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.search_incidents_service",
        fake_search,
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.async_session_factory",
        lambda: fake_session_context,
    )

    async with Client(
        mcp,
        raise_exceptions=True,
    ) as client:
        result = await client.call_tool(
            "search_incidents",
            {
                "organization_id": str(ORGANIZATION_ID),
                "query": "duplicate payment",
                "limit": 5,
            },
        )

    fake_search.assert_awaited_once_with(
        session=fake_session_context.session,
        organization_id=ORGANIZATION_ID,
        query="duplicate payment",
        limit=5,
    )

    assert result.structured_content == {
        "query": "duplicate payment",
        "incidents": [],
    }


@pytest.mark.anyio
async def test_get_incident_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)

    fake_access_token = SimpleNamespace(
        token="valid-token",
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.get_access_token",
        lambda: fake_access_token,
    )

    fake_authenticate = AsyncMock(
        return_value=MCPAuthenticatedContext(
            user_id=USER_ID,
            organization_id=ORGANIZATION_ID,
            role=MembershipRole.OPERATOR,
        )
    )

    fake_get = AsyncMock(
        return_value=MCPIncidentDetail(
            id=INCIDENT_ID,
            organization_id=ORGANIZATION_ID,
            title="Customer charged twice",
            description=("Customer reports two charges."),
            status=IncidentStatus.INVESTIGATING,
            category="payment",
            priority=IncidentPriority.HIGH,
            subject_customer_id=None,
            created_at=now,
            updated_at=now,
        )
    )

    fake_session_context = FakeSessionContext()

    monkeypatch.setattr(
        "ops_pilot.mcp.server.authenticate_mcp_access",
        fake_authenticate,
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.get_incident_detail_service",
        fake_get,
    )

    monkeypatch.setattr(
        "ops_pilot.mcp.server.async_session_factory",
        lambda: fake_session_context,
    )

    async with Client(
        mcp,
        raise_exceptions=True,
    ) as client:
        result = await client.call_tool(
            "get_incident",
            {
                "organization_id": str(ORGANIZATION_ID),
                "incident_id": str(INCIDENT_ID),
            },
        )

    fake_get.assert_awaited_once_with(
        session=fake_session_context.session,
        organization_id=ORGANIZATION_ID,
        incident_id=INCIDENT_ID,
    )

    assert result.structured_content is not None

    incident = result.structured_content["incident"]

    assert incident is not None
    assert incident["id"] == str(INCIDENT_ID)
    assert incident["title"] == "Customer charged twice"
