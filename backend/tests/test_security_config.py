from typing import Any

import pytest
from pydantic import ValidationError

from ops_pilot.core.config import Settings


def make_settings(
    **overrides: object,
) -> Settings:
    values: dict[str, Any] = {
        "environment": "development",
        "database_url": "postgresql+asyncpg://user:pass@localhost/db",
        "redis_url": "redis://localhost:6379/0",
        "jwt_secret_key": "a" * 32,
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
        "aws_region": "us-east-1",
        "s3_bucket_name": "test-bucket",
        "qdrant_url": "http://localhost:6333",
        "qdrant_api_key": "test-qdrant-key",
        "mistral_api_key": "test-mistral-key",
        "voyage_api_key": "test-voyage-key",
        "groq_api_key": "test-groq-key",
    }

    values.update(overrides)

    return Settings(
        **values,
    )


def test_rejects_short_jwt_secret() -> None:
    with pytest.raises(
        ValidationError,
        match="JWT_SECRET_KEY",
    ):
        make_settings(
            jwt_secret_key="short-secret",
        )


def test_rejects_unsupported_jwt_algorithm() -> None:
    with pytest.raises(
        ValidationError,
        match="JWT_ALGORITHM",
    ):
        make_settings(
            jwt_algorithm="none",
        )


def test_rejects_wildcard_mcp_hosts() -> None:
    with pytest.raises(
        ValidationError,
        match="MCP_ALLOWED_HOSTS",
    ):
        make_settings(
            mcp_allowed_hosts="*",
        )


def test_rejects_wildcard_mcp_origins() -> None:
    with pytest.raises(
        ValidationError,
        match="MCP_ALLOWED_ORIGINS",
    ):
        make_settings(
            mcp_allowed_origins="*",
        )


def test_production_requires_https_mcp_authorization_server() -> None:
    with pytest.raises(
        ValidationError,
        match="authorization server must use HTTPS",
    ):
        make_settings(
            environment="production",
            mcp_authorization_server_url=("http://example.com"),
            mcp_resource_url=("https://example.com/mcp"),
            inngest_dev=False,
        )


def test_production_requires_https_mcp_resource() -> None:
    with pytest.raises(
        ValidationError,
        match="resource URL must use HTTPS",
    ):
        make_settings(
            environment="production",
            mcp_authorization_server_url=("https://example.com"),
            mcp_resource_url=("http://example.com/mcp"),
            inngest_dev=False,
        )


def test_production_rejects_inngest_dev_mode() -> None:
    with pytest.raises(
        ValidationError,
        match="INNGEST_DEV",
    ):
        make_settings(
            environment="production",
            mcp_authorization_server_url=("https://example.com"),
            mcp_resource_url=("https://example.com/mcp"),
            inngest_dev=True,
        )


def test_valid_production_security_config() -> None:
    settings = make_settings(
        environment="production",
        mcp_authorization_server_url=("https://ops.example.com"),
        mcp_resource_url=("https://ops.example.com/mcp"),
        mcp_allowed_hosts=("ops.example.com"),
        mcp_allowed_origins=("https://chatgpt.com"),
        inngest_dev=False,
    )

    assert settings.environment == "production"
