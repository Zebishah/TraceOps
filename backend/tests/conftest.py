import os

TEST_ENV = {
    "DATABASE_URL": ("postgresql+psycopg://test:test@localhost/test"),
    "REDIS_URL": "redis://localhost:6379/15",
    "JWT_SECRET_KEY": ("test-secret-key-used-only-for-tests-123456"),
    "AWS_ACCESS_KEY_ID": "test-access-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret-key",
    "AWS_REGION": "us-east-1",
    "S3_BUCKET_NAME": "test-bucket",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_API_KEY": "test-qdrant-key",
    "MISTRAL_API_KEY": "test-mistral-key",
    "VOYAGE_API_KEY": "test-voyage-key",
    "GROQ_API_KEY": "test-groq-key",
}


for key, value in TEST_ENV.items():
    os.environ.setdefault(
        key,
        value,
    )
