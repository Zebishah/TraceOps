import asyncio
import os
import uuid

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {
    "ops_pilot_health",
    "search_project_knowledge",
    "list_open_incidents",
    "search_incidents",
    "get_incident",
    "get_customer",
    "list_customer_orders",
    "get_order",
    "list_order_payments",
    "get_payment_transaction",
    "search_incident_memory",
    "list_my_organizations",
    "investigate_incident",
}


def require_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"{name} is required.")

    return value


async def main() -> None:
    mcp_url = os.getenv(
        "OPSPILOT_MCP_URL",
        "http://localhost:8000/mcp",
    )

    token = require_env(
        "OPSPILOT_MCP_TOKEN",
    )

    # organization_id = require_env(
    #     "OPSPILOT_ORG_ID",
    # )

    async with httpx2.AsyncClient(
        headers={
            "Authorization": f"Bearer {token}",
        },
        timeout=httpx2.Timeout(
            30.0,
            read=300.0,
        ),
    ) as http_client:
        transport = streamable_http_client(
            mcp_url,
            http_client=http_client,
        )

        async with Client(transport) as client:
            print()
            print("=== MCP CONNECTED ===")

            if client.server_info is None:
                raise RuntimeError("MCP server returned no server information.")

            print(
                "Server:",
                client.server_info.name,
            )

            tools_result = await client.list_tools()

            tool_names = {tool.name for tool in tools_result.tools}

            missing_tools = EXPECTED_TOOLS - tool_names

            if missing_tools:
                raise RuntimeError(f"Missing expected MCP tools: {sorted(missing_tools)}")

            print()
            print("=== TOOL DISCOVERY PASSED ===")
            print(f"Discovered {len(tool_names)} tools.")

            health_result = await client.call_tool(
                "ops_pilot_health",
                {},
            )

            if health_result.is_error:
                raise RuntimeError("ops_pilot_health returned an MCP error.")

            health = health_result.structured_content

            if health is None:
                raise RuntimeError("Health tool returned no structured content.")

            if health.get("status") != "ok":
                raise RuntimeError(f"Unexpected health response: {health}")

            print()
            print("=== HEALTH PASSED ===")
            print(f"Service: {health.get('service')}")

            incidents_result = await client.call_tool(
                "list_open_incidents",
                {
                    "limit": 10,
                },
            )

            if incidents_result.is_error:
                raise RuntimeError("Authorized incident read failed.")

            incidents_payload = incidents_result.structured_content

            if incidents_payload is None:
                raise RuntimeError("Incident tool returned no structured content.")

            incidents = incidents_payload.get("incidents")

            if not isinstance(
                incidents,
                list,
            ):
                raise RuntimeError("Incident response has an unexpected shape.")

            print()
            print("=== AUTHORIZED TENANT READ PASSED ===")
            print(f"Open incidents returned: {len(incidents)}")

            fake_organization_id = str(uuid.uuid4())

            cross_tenant_result = await client.call_tool(
                "list_open_incidents",
                {
                    "organization_id": fake_organization_id,
                    "limit": 10,
                },
            )

            if not cross_tenant_result.is_error:
                raise RuntimeError("Cross-tenant request was unexpectedly allowed.")

            print()
            print("=== CROSS-TENANT ISOLATION PASSED ===")

            print()
            print("=== MCP HTTP SMOKE TEST PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
