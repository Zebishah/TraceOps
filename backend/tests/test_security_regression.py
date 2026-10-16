from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = BACKEND_ROOT / "src" / "ops_pilot"


def test_mcp_server_does_not_expose_direct_refund_tool() -> None:
    server_source = (SOURCE_ROOT / "mcp" / "server.py").read_text()

    forbidden_tool_names = {
        "refund_transaction",
        "execute_refund",
        "execute_approved_refund",
        "direct_refund",
    }

    for tool_name in forbidden_tool_names:
        assert f"@mcp.tool()\nasync def {tool_name}" not in server_source


def test_refund_execution_is_not_imported_by_api_routes() -> None:
    routes_dir = SOURCE_ROOT / "api" / "routes"

    for route_file in routes_dir.glob("*.py"):
        source = route_file.read_text()

        assert "execute_approved_refund" not in source, (
            f"Direct refund execution exposed from {route_file.name}"
        )


def test_source_does_not_print_sensitive_credentials() -> None:
    sensitive_names = {
        "jwt_secret_key",
        "aws_secret_access_key",
        "mistral_api_key",
        "voyage_api_key",
        "groq_api_key",
        "qdrant_api_key",
        "n8n_webhook_secret",
        "inngest_signing_key",
    }

    for source_file in SOURCE_ROOT.rglob("*.py"):
        source = source_file.read_text()

        for secret_name in sensitive_names:
            assert f"print({secret_name}" not in source

            assert f"print(settings.{secret_name}" not in source


def test_mcp_auth_uses_mcp_specific_token_validation() -> None:
    mcp_auth_source = (SOURCE_ROOT / "services" / "mcp_auth.py").read_text()

    assert "decode_mcp_access_token" in mcp_auth_source

    assert "decode_access_token(" not in mcp_auth_source
