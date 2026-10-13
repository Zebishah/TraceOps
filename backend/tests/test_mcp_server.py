import pytest
from mcp import Client

from ops_pilot.mcp.server import mcp
from ops_pilot.schemas.project_knowledge import (
    ProjectKnowledgeResult,
)


@pytest.mark.anyio
async def test_mcp_health_tool() -> None:
    async with Client(
        mcp,
        raise_exceptions=True,
    ) as client:
        tools = await client.list_tools()

        tool_names = {tool.name for tool in tools.tools}

        assert "ops_pilot_health" in tool_names

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
