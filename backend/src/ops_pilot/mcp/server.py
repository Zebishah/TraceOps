import uuid
from typing import Annotated

from mcp.server.auth.middleware.auth_context import (
    get_access_token,
)
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from ops_pilot.core.config import get_settings
from ops_pilot.db.session import async_session_factory
from ops_pilot.mcp.auth import OpsPilotMCPTokenVerifier
from ops_pilot.schemas.mcp_incidents import (
    MCPIncidentDetailResponse,
    MCPIncidentSearchResponse,
)
from ops_pilot.schemas.mcp_operational import (
    MCPCustomerResponse,
    MCPIncidentMemoryResponse,
    MCPOrderResponse,
    MCPOrdersResponse,
    MCPPaymentResponse,
    MCPPaymentsResponse,
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
from ops_pilot.services.mcp_operational import (
    get_customer as get_customer_service,
)
from ops_pilot.services.mcp_operational import (
    get_order_for_mcp as get_order_service,
)
from ops_pilot.services.mcp_operational import (
    get_payment_transaction_for_mcp as get_payment_transaction_service,
)
from ops_pilot.services.mcp_operational import (
    list_customer_orders_for_mcp as list_customer_orders_service,
)
from ops_pilot.services.mcp_operational import (
    list_order_payments_for_mcp as list_order_payments_service,
)
from ops_pilot.services.mcp_operational import (
    search_incident_memory_for_mcp as search_incident_memory_service,
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


settings = get_settings()

mcp = MCPServer(
    "OpsPilot",
    instructions=(
        "OpsPilot provides secure incident investigation, "
        "project knowledge, and operational support tools."
    ),
    token_verifier=OpsPilotMCPTokenVerifier(),
    auth=AuthSettings(
        issuer_url=settings.mcp_issuer_url,
        resource_server_url=settings.mcp_resource_url,
        required_scopes=[
            settings.mcp_required_scope,
        ],
        validate_token_resource=True,
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


@mcp.tool()
async def get_customer(
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> MCPCustomerResponse:
    """Get a customer from an organization the caller can access."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        customer = await get_customer_service(
            session=session,
            organization_id=auth_context.organization_id,
            customer_id=customer_id,
        )

    return MCPCustomerResponse(
        customer=customer,
    )


@mcp.tool()
async def list_customer_orders(
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=20,
        ),
    ] = 10,
) -> MCPOrdersResponse:
    """List recent orders for a customer the caller can access."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        orders = await list_customer_orders_service(
            session=session,
            organization_id=auth_context.organization_id,
            customer_id=customer_id,
            limit=limit,
        )

    return MCPOrdersResponse(
        orders=orders,
    )


@mcp.tool()
async def get_order(
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_order_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
        ),
    ],
) -> MCPOrderResponse:
    """Get one operational order for an authorized customer."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        order = await get_order_service(
            session=session,
            organization_id=auth_context.organization_id,
            customer_id=customer_id,
            external_order_id=external_order_id,
        )

    return MCPOrderResponse(
        order=order,
    )


@mcp.tool()
async def list_order_payments(
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_order_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
        ),
    ],
) -> MCPPaymentsResponse:
    """List payments for an authorized customer's order."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        payments = await list_order_payments_service(
            session=session,
            organization_id=auth_context.organization_id,
            customer_id=customer_id,
            external_order_id=external_order_id,
        )

    return MCPPaymentsResponse(
        payments=payments,
    )


@mcp.tool()
async def get_payment_transaction(
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_transaction_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=160,
        ),
    ],
) -> MCPPaymentResponse:
    """Get one payment transaction for an authorized customer."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        payment = await get_payment_transaction_service(
            session=session,
            organization_id=auth_context.organization_id,
            customer_id=customer_id,
            external_transaction_id=external_transaction_id,
        )

    return MCPPaymentResponse(
        payment=payment,
    )


@mcp.tool()
async def search_incident_memory(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=10,
        ),
    ] = 3,
) -> MCPIncidentMemoryResponse:

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        memories = await search_incident_memory_service(
            session=session,
            organization_id=auth_context.organization_id,
            incident_id=incident_id,
            limit=limit,
        )

    return MCPIncidentMemoryResponse(
        incident_id=incident_id,
        memories=memories,
    )
