"""Supported IncidentIQ MCP OAuth scopes."""

READ_SCOPE = "ops-pilot:read"
WRITE_SCOPE = "ops-pilot:write"

SUPPORTED_MCP_SCOPES = frozenset({READ_SCOPE, WRITE_SCOPE})


def parse_mcp_scopes(value: str) -> list[str]:
    """Parse a scope string without accepting duplicates."""
    scopes = value.split()

    if len(scopes) != len(set(scopes)):
        raise ValueError("Duplicate OAuth scopes are not allowed")

    if not scopes:
        raise ValueError("At least one OAuth scope is required")

    if not set(scopes).issubset(SUPPORTED_MCP_SCOPES):
        raise ValueError("Unsupported OAuth scope")

    if READ_SCOPE not in scopes:
        raise ValueError("MCP clients must request the read scope")

    return scopes


def validate_mcp_scope_grant(
    requested: str,
    registered: str,
) -> list[str]:
    """Require requested scopes to be registered by the client."""
    requested_scopes = parse_mcp_scopes(requested)
    registered_scopes = parse_mcp_scopes(registered)

    if not set(requested_scopes).issubset(set(registered_scopes)):
        raise ValueError("Requested OAuth scopes exceed client registration")

    return requested_scopes
