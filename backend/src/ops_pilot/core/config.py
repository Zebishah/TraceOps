from functools import lru_cache

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OpsPilot API"
    app_version: str = "0.1.0"
    environment: str = "development"

    database_url: str
    redis_url: str
    redis_key_prefix: str = "ops_pilot"
    redis_default_ttl_seconds: int = 300
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    mcp_authorization_server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    mcp_resource_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000/mcp")
    mcp_required_scope: str = "ops-pilot:read"
    mcp_access_token_expire_minutes: int = 1440
    mcp_authorization_code_expire_minutes: int = 10
    mcp_refresh_token_expire_days: int = 30
    mcp_allowed_hosts: str = "localhost,127.0.0.1"
    mcp_allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    s3_bucket_name: str

    log_level: str = "INFO"

    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection_name: str = "ops_pilot_document_chunks_v2"
    qdrant_memory_collection_name: str = "ops_pilot_incident_memories_v1"
    qdrant_project_knowledge_collection_name: str = "ops_pilot_project_knowledge_v1"

    inngest_event_key: str | None = None
    inngest_signing_key: str | None = None
    inngest_dev: bool = True

    mistral_api_key: str
    embedding_model: str = "mistral-embed"
    embedding_dimension: int = 1024
    enable_approval_resume_cron: bool = False

    # Financial recovery remains disabled by default.
    enable_production_approval_recovery: bool = False

    # Runtime kill switch. False blocks financial recovery
    # even if the scheduler has been registered.
    approval_recovery_execution_enabled: bool = False

    # Operational monitoring thresholds.
    approval_recovery_quarantine_alert_count: int = 1
    approval_recovery_quarantine_age_alert_seconds: int = 3600
    approval_recovery_processing_alert_count: int = 25

    mistral_timeout_seconds: float = 30.0
    voyage_timeout_seconds: float = 30.0
    groq_timeout_seconds: float = 30.0

    voyage_api_key: str
    reranker_model: str = "rerank-3-lite"
    retrieval_candidate_limit: int = 12
    n8n_delivery_enabled: bool = True
    n8n_webhook_base_url: str | None = None
    n8n_webhook_secret: str | None = None
    n8n_timeout_seconds: float = 10.0

    groq_api_key: str
    generation_model: str = "qwen/qwen3.8-27b"
    database_pool_size: int = Field(default=3, ge=1, le=50)
    database_max_overflow: int = Field(default=2, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_connect_timeout_seconds: int = Field(default=10, ge=1, le=120)

    health_dependency_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        environment = self.environment.lower()

        if len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")

        if self.jwt_algorithm != "HS256":
            raise ValueError("JWT_ALGORITHM must be HS256")

        if self.access_token_expire_minutes <= 0:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be greater than 0")

        if self.mcp_access_token_expire_minutes <= 0:
            raise ValueError("MCP_ACCESS_TOKEN_EXPIRE_MINUTES must be greater than 0")

        if self.mcp_authorization_code_expire_minutes <= 0:
            raise ValueError("MCP_AUTHORIZATION_CODE_EXPIRE_MINUTES must be greater than 0")

        if self.mcp_refresh_token_expire_days <= 0:
            raise ValueError("MCP_REFRESH_TOKEN_EXPIRE_DAYS must be greater than 0")
        if self.mistral_timeout_seconds <= 0:
            raise ValueError("MISTRAL_TIMEOUT_SECONDS must be greater than 0")

        if self.voyage_timeout_seconds <= 0:
            raise ValueError("VOYAGE_TIMEOUT_SECONDS must be greater than 0")

        if self.n8n_timeout_seconds <= 0:
            raise ValueError("N8N_TIMEOUT_SECONDS must be greater than 0")

        if self.groq_timeout_seconds <= 0:
            raise ValueError("GROQ_TIMEOUT_SECONDS must be greater than 0")
        allowed_hosts = {host.strip() for host in self.mcp_allowed_hosts.split(",") if host.strip()}

        allowed_origins = {
            origin.strip() for origin in self.mcp_allowed_origins.split(",") if origin.strip()
        }

        if "*" in allowed_hosts:
            raise ValueError("MCP_ALLOWED_HOSTS must not contain wildcard '*'")

        if "*" in allowed_origins:
            raise ValueError("MCP_ALLOWED_ORIGINS must not contain wildcard '*'")

        # The approval recovery cron is currently staging-only.
        # Do not silently accept a production setting that
        # cannot actually register the scheduler.
        if environment == "production" and self.enable_approval_resume_cron:
            raise ValueError(
                "ENABLE_APPROVAL_RESUME_CRON cannot be enabled "
                "in production until production scheduler "
                "registration is explicitly implemented"
            )

        if environment == "production":
            authorization_url = str(self.mcp_authorization_server_url)

            resource_url = str(self.mcp_resource_url)

            if not authorization_url.startswith("https://"):
                raise ValueError("Production MCP authorization server must use HTTPS")

            if self.approval_recovery_quarantine_alert_count < 1:
                raise ValueError("APPROVAL_RECOVERY_QUARANTINE_ALERT_COUNT must be positive")

            if self.approval_recovery_quarantine_age_alert_seconds < 1:
                raise ValueError("APPROVAL_RECOVERY_QUARANTINE_AGE_ALERT_SECONDS must be positive")

            if self.approval_recovery_processing_alert_count < 1:
                raise ValueError("APPROVAL_RECOVERY_PROCESSING_ALERT_COUNT must be positive")

            # Registration and execution are distinct safety gates.
            # Do not allow the execution flag by itself to activate
            # financial recovery on a production deployment.
            if (
                environment == "production"
                and self.approval_recovery_execution_enabled
                and not self.enable_production_approval_recovery
            ):
                raise ValueError(
                    "Production financial recovery execution requires "
                    "ENABLE_PRODUCTION_APPROVAL_RECOVERY"
                )

            # Production registration is intentionally not yet enabled.
            # This guard will remain until the R04 proof, staging
            # canary and operational alert verification pass.
            if (
                environment == "production"
                and self.approval_recovery_execution_enabled
                and not self.enable_production_approval_recovery
            ):
                raise ValueError(
                    "Production financial recovery execution requires "
                    "ENABLE_PRODUCTION_APPROVAL_RECOVERY"
                )

            if not resource_url.startswith("https://"):
                raise ValueError("Production MCP resource URL must use HTTPS")

            if self.inngest_dev:
                raise ValueError("INNGEST_DEV must be false in production")

            if not self.inngest_event_key or not self.inngest_event_key.strip():
                raise ValueError("INNGEST_EVENT_KEY is required in production")

            if not self.inngest_signing_key or not self.inngest_signing_key.strip():
                raise ValueError("INNGEST_SIGNING_KEY is required in production")

            if self.n8n_webhook_base_url is not None:
                n8n_url = self.n8n_webhook_base_url.strip()

                if not n8n_url.startswith("https://"):
                    raise ValueError("Production n8n webhook URL must use HTTPS")

                if not self.n8n_webhook_secret or not self.n8n_webhook_secret.strip():
                    raise ValueError(
                        "N8N_WEBHOOK_SECRET is required when "
                        "production n8n integration is configured"
                    )

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
