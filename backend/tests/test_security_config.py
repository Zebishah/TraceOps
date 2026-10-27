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
        "test_database_url": "postgresql+asyncpg://user:pass@localhost/test_db",
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
        "inngest_event_key": "test-event-key",
        "inngest_signing_key": "test-signing-key",
        "n8n_webhook_base_url": None,
        "n8n_webhook_secret": None,
    }

    values.update(overrides)

    return Settings(
        _env_file=None,
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


def test_production_rejects_staging_only_approval_cron() -> None:
    with pytest.raises(
        ValidationError,
        match="ENABLE_APPROVAL_RESUME_CRON",
    ):
        make_settings(
            environment="production",
            mcp_authorization_server_url="https://ops.example.com",
            mcp_resource_url="https://ops.example.com/mcp",
            inngest_dev=False,
            enable_approval_resume_cron=True,
        )


def test_staging_can_enable_approval_cron() -> None:
    settings = make_settings(
        environment="staging",
        enable_approval_resume_cron=True,
    )

    assert settings.enable_approval_resume_cron is True


def test_production_keeps_approval_cron_disabled() -> None:
    settings = make_settings(
        environment="production",
        mcp_authorization_server_url="https://ops.example.com",
        mcp_resource_url="https://ops.example.com/mcp",
        inngest_dev=False,
        enable_approval_resume_cron=False,
    )

    assert settings.enable_approval_resume_cron is False


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "mcp_authorization_server_url": "https://ops.example.com",
        "mcp_resource_url": "https://ops.example.com/mcp",
        "mcp_allowed_hosts": "ops.example.com",
        "mcp_allowed_origins": "https://chatgpt.com",
        "inngest_dev": False,
    }
    values.update(overrides)
    return make_settings(**values)


def test_production_requires_inngest_event_key() -> None:
    with pytest.raises(ValidationError, match="INNGEST_EVENT_KEY"):
        production_settings(inngest_event_key=None)


def test_production_requires_inngest_signing_key() -> None:
    with pytest.raises(ValidationError, match="INNGEST_SIGNING_KEY"):
        production_settings(inngest_signing_key=None)


def test_production_rejects_http_n8n_webhook() -> None:
    with pytest.raises(
        ValidationError,
        match="n8n webhook URL must use HTTPS",
    ):
        production_settings(
            n8n_webhook_base_url="http://n8n.example.com",
            n8n_webhook_secret="test-secret",
        )


def test_production_requires_secret_for_configured_n8n() -> None:
    with pytest.raises(
        ValidationError,
        match="N8N_WEBHOOK_SECRET",
    ):
        production_settings(
            n8n_webhook_base_url="https://n8n.example.com",
            n8n_webhook_secret=None,
        )


def test_production_accepts_secure_n8n_config() -> None:
    settings = production_settings(
        n8n_webhook_base_url="https://n8n.example.com",
        n8n_webhook_secret="test-secret",
    )

    assert settings.inngest_dev is False
    assert settings.n8n_webhook_secret == "test-secret"
