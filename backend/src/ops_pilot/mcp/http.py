from mcp.server.transport_security import (
    TransportSecuritySettings,
)
from starlette.applications import Starlette

from ops_pilot.core.config import get_settings
from ops_pilot.mcp.server import mcp


def build_mcp_http_app() -> Starlette:
    settings = get_settings()

    allowed_hosts = [
        value.strip() for value in settings.mcp_allowed_hosts.split(",") if value.strip()
    ]

    allowed_origins = [
        value.strip() for value in settings.mcp_allowed_origins.split(",") if value.strip()
    ]

    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )


mcp_http_app = build_mcp_http_app()
