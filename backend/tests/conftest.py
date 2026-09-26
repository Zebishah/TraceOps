import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@localhost/test",
)

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-used-only-for-tests",
)
