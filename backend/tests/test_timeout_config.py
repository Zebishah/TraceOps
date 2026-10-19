from typing import Any

import pytest
from pydantic import ValidationError

from ops_pilot.core.config import Settings


def make_settings(
    **overrides: Any,
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

    return Settings(**values)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        (
            "mistral_timeout_seconds",
            "MISTRAL_TIMEOUT_SECONDS",
        ),
        (
            "voyage_timeout_seconds",
            "VOYAGE_TIMEOUT_SECONDS",
        ),
        (
            "n8n_timeout_seconds",
            "N8N_TIMEOUT_SECONDS",
        ),
        (
            "groq_timeout_seconds",
            "GROQ_TIMEOUT_SECONDS",
        ),
    ],
)
def test_provider_timeout_must_be_positive(
    field: str,
    message: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match=message,
    ):
        make_settings(
            **{
                field: 0,
            }
        )


def test_provider_timeout_configuration_is_accepted() -> None:
    settings = make_settings(
        mistral_timeout_seconds=20.0,
        voyage_timeout_seconds=25.0,
        n8n_timeout_seconds=8.0,
        groq_timeout_seconds=35.0,
    )

    assert settings.mistral_timeout_seconds == 20.0
    assert settings.voyage_timeout_seconds == 25.0
    assert settings.n8n_timeout_seconds == 8.0
    assert settings.groq_timeout_seconds == 35.0
