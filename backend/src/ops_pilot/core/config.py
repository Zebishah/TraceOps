from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OpsPilot API"
    app_version: str = "0.1.0"
    environment: str = "development"

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    s3_bucket_name: str

    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection_name: str = "ops_pilot_document_chunks_v1"

    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dimension: int = 1024

    hf_token: str | None = None

    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    retrieval_candidate_limit: int = 12

    groq_api_key: str

    generation_model: str = "qwen/qwen3.8-27b"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
