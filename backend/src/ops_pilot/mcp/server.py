from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from ops_pilot.schemas.project_knowledge import (
    ProjectKnowledgeSearchResponse,
)
from ops_pilot.services.project_knowledge import (
    search_project_knowledge as search_project_knowledge_service,
)


class OpsPilotHealthResult(BaseModel):
    status: str
    service: str


mcp = MCPServer(
    "OpsPilot",
    instructions=(
        "OpsPilot provides secure incident investigation, "
        "project knowledge, and operational support tools."
    ),
)


@mcp.tool()
async def ops_pilot_health() -> OpsPilotHealthResult:
    """Check whether the OpsPilot MCP server is available."""

    return OpsPilotHealthResult(
        status="ok",
        service="ops-pilot-mcp",
    )


@mcp.tool()
async def search_project_knowledge(
    query: str,
    limit: int = 5,
) -> ProjectKnowledgeSearchResponse:
    """This tool searches OpsPilot architecture and implementation knowledge.
    We use this tool when the user asks how OpsPilot works, why a
    technology was chosen, how a feature was implemented, or how
    parts of the architecture interact.
    """
    results = await search_project_knowledge_service(
        query=query,
        limit=limit,
    )

    return ProjectKnowledgeSearchResponse(
        query=query,
        results=results,
    )
