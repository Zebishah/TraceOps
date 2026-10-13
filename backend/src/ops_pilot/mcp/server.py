import uuid
from typing import Annotated

from mcp.server.auth.middleware.auth_context import (
    get_access_token,
)
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from ops_pilot.db.session import async_session_factory
from ops_pilot.schemas.mcp_incidents import (
    MCPIncidentDetailResponse,
    MCPIncidentSearchResponse,
)
from ops_pilot.schemas.project_knowledge import (
    ProjectKnowledgeSearchResponse,
)
from ops_pilot.services.mcp_auth import (
    MCPAuthenticationError,
    authenticate_mcp_access,
)
from ops_pilot.services.mcp_incidents import (
    get_incident_detail as get_incident_detail_service,
)
from ops_pilot.services.mcp_incidents import (
    list_open_incidents as list_open_incidents_service,
)
from ops_pilot.services.mcp_incidents import (
    search_incidents as search_incidents_service,
)
from ops_pilot.services.project_knowledge import (
    search_project_knowledge as search_project_knowledge_service,
)


class OpsPilotHealthResult(BaseModel):
    status: str
    service: str


def get_mcp_bearer_token() -> str:
    access_token = get_access_token()

    if access_token is None:
        raise MCPAuthenticationError("Authentication is required for operational MCP tools")

    return access_token.token


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
    """Search OpsPilot architecture and implementation knowledge."""

    results = await search_project_knowledge_service(
        query=query,
        limit=limit,
    )

    return ProjectKnowledgeSearchResponse(
        query=query,
        results=results,
    )


@mcp.tool()
async def list_open_incidents(
    organization_id: uuid.UUID,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=50,
        ),
    ] = 20,
) -> MCPIncidentSearchResponse:
    """List open incidents for an organization the caller can access."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        incidents = await list_open_incidents_service(
            session=session,
            organization_id=auth_context.organization_id,
            limit=limit,
        )

    return MCPIncidentSearchResponse(
        incidents=incidents,
    )


@mcp.tool()
async def search_incidents(
    organization_id: uuid.UUID,
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
        ),
    ],
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=50,
        ),
    ] = 20,
) -> MCPIncidentSearchResponse:
    """Search incidents in an organization the caller can access."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        incidents = await search_incidents_service(
            session=session,
            organization_id=auth_context.organization_id,
            query=query,
            limit=limit,
        )

    return MCPIncidentSearchResponse(
        query=query,
        incidents=incidents,
    )


@mcp.tool()
async def get_incident(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> MCPIncidentDetailResponse:
    """Get one incident from an organization the caller can access."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        incident = await get_incident_detail_service(
            session=session,
            organization_id=auth_context.organization_id,
            incident_id=incident_id,
        )

    return MCPIncidentDetailResponse(
        incident=incident,
    )
