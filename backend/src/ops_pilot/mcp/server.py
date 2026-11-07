import uuid
from typing import Annotated

from mcp.server.auth.middleware.auth_context import (
    get_access_token,
)
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from ops_pilot.core.config import get_settings
from ops_pilot.core.mcp_scopes import WRITE_SCOPE
from ops_pilot.db.session import async_session_factory
from ops_pilot.mcp.auth import OpsPilotMCPTokenVerifier
from ops_pilot.schemas.incidents import (
    IncidentInvestigationResponse,
)
from ops_pilot.schemas.mcp_auth import (
    MCPOrganizationsResponse,
)
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
    list_mcp_organizations,
    require_mcp_investigation_role,
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
from ops_pilot.services.mcp_investigation import (
    investigate_incident_for_mcp as investigate_incident_service,
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


def require_mcp_write_scope(
    access_token: str,
) -> None:
    """Verify write permission from the signed MCP JWT."""

    import jwt

    from ops_pilot.core.security import decode_mcp_access_token

    try:
        claims = decode_mcp_access_token(access_token)
    except (jwt.PyJWTError, ValueError) as exc:
        raise MCPAuthenticationError("Invalid MCP access token") from exc

    scope_value = claims.get("scope")

    if not isinstance(scope_value, str):
        raise MCPAuthenticationError("MCP access token has no valid scope claim")

    if WRITE_SCOPE not in scope_value.split():
        raise MCPAuthenticationError("MCP investigation requires ops-pilot:write scope")


settings = get_settings()

mcp = MCPServer(
    "IncidentIQ",
    instructions=(
        "IncidentIQ provides secure incident investigation, project knowledge, "
        "and operational support tools. For tenant-scoped operations, omit "
        "organization_id unless the user explicitly selected an organization. "
        "The server automatically resolves a single authorized organization. "
        "If multiple organizations are available, call list_my_organizations "
        "before asking the user to choose one. Never invent organization IDs. "
        "Sensitive incident actions remain subject to IncidentIQ authorization "
        "and human approval."
    ),
    token_verifier=OpsPilotMCPTokenVerifier(),
    auth=AuthSettings(
        issuer_url=settings.mcp_authorization_server_url,
        resource_server_url=settings.mcp_resource_url,
        required_scopes=[
            settings.mcp_required_scope,
        ],
        validate_token_resource=True,
    ),
)


@mcp.tool()
async def ops_pilot_health() -> OpsPilotHealthResult:
    """Check whether the IncidentIQ MCP server is available."""

    return OpsPilotHealthResult(
        status="ok",
        service="ops-pilot-mcp",
    )


@mcp.tool()
async def list_my_organizations() -> MCPOrganizationsResponse:
    """List organizations available to the authenticated IncidentIQ user."""

    access_token = get_mcp_bearer_token()
    require_mcp_write_scope(access_token)
    async with async_session_factory() as session:
        organizations = await list_mcp_organizations(
            session=session,
            access_token=access_token,
        )

    return MCPOrganizationsResponse(
        organizations=organizations,
    )


@mcp.tool()
async def search_project_knowledge(
    query: Annotated[
        str,
        Field(min_length=1, max_length=500),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=20),
    ] = 5,
) -> ProjectKnowledgeSearchResponse:
    """Search shared project knowledge for an authenticated member."""

    access_token = get_mcp_bearer_token()

    async with async_session_factory() as session:
        organizations = await list_mcp_organizations(
            session=session,
            access_token=access_token,
        )

        if not organizations:
            raise MCPAuthenticationError("An active organization membership is required")

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
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=50,
        ),
    ] = 20,
    organization_id: uuid.UUID | None = None,
) -> MCPIncidentSearchResponse:

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
    organization_id: uuid.UUID | None = None,
) -> MCPIncidentSearchResponse:

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
    incident_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> MCPIncidentDetailResponse:

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
    customer_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> MCPCustomerResponse:

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
    customer_id: uuid.UUID,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=20,
        ),
    ] = 10,
    organization_id: uuid.UUID | None = None,
) -> MCPOrdersResponse:

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
    customer_id: uuid.UUID,
    external_order_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
        ),
    ],
    organization_id: uuid.UUID | None = None,
) -> MCPOrderResponse:

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
    customer_id: uuid.UUID,
    external_order_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
        ),
    ],
    organization_id: uuid.UUID | None = None,
) -> MCPPaymentsResponse:

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
    customer_id: uuid.UUID,
    external_transaction_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=160,
        ),
    ],
    organization_id: uuid.UUID | None = None,
) -> MCPPaymentResponse:

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
    incident_id: uuid.UUID,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=10,
        ),
    ] = 3,
    organization_id: uuid.UUID | None = None,
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


@mcp.tool()
async def investigate_incident(
    incident_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> IncidentInvestigationResponse | None:
    """Investigate an incident with both OAuth and organization authorization."""

    # 1. Retrieve the bearer token from the MCP request.
    access_token = get_mcp_bearer_token()

    # 2. Verify the signed JWT explicitly grants write access.
    # This MUST happen before opening a database session.
    require_mcp_write_scope(access_token)

    # 3. Verify user identity and organization membership.
    async with async_session_factory() as session:
        auth_context = await authenticate_mcp_access(
            session=session,
            access_token=access_token,
            organization_id=organization_id,
        )

        # 4. Verify the user's organization role permits investigation.
        require_mcp_investigation_role(auth_context)

        # 5. Only now perform the state-changing investigation.
        investigation = await investigate_incident_service(
            session=session,
            organization_id=auth_context.organization_id,
            incident_id=incident_id,
        )

    return investigation
