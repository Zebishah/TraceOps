"""D08: S3 document download limits."""

from io import BytesIO

import pytest

from ops_pilot.core.exceptions import DocumentTooLargeError
from ops_pilot.storage.s3 import (
    MAX_S3_DOCUMENT_DOWNLOAD_BYTES,
    S3Storage,
)


@pytest.mark.anyio
async def test_s3_rejects_oversized_reported_length() -> None:
    body = BytesIO(b"content")

    class Client:
        def get_object(self, *, Bucket, Key):
            return {
                "ContentLength": (MAX_S3_DOCUMENT_DOWNLOAD_BYTES + 1),
                "Body": body,
            }

    storage = object.__new__(S3Storage)
    storage.bucket_name = "test-bucket"
    storage.client = Client()

    with pytest.raises(DocumentTooLargeError):
        await storage.download_file(key="test.pdf")

    assert body.closed


@pytest.mark.anyio
async def test_s3_rejects_oversized_actual_body() -> None:
    body = BytesIO(b"x" * (MAX_S3_DOCUMENT_DOWNLOAD_BYTES + 1))

    class Client:
        def get_object(self, *, Bucket, Key):
            return {"Body": body}

    storage = object.__new__(S3Storage)
    storage.bucket_name = "test-bucket"
    storage.client = Client()

    with pytest.raises(DocumentTooLargeError):
        await storage.download_file(key="test.pdf")

    assert body.closed


@pytest.mark.anyio
async def test_s3_accepts_valid_document() -> None:
    content = b"%PDF-1.7\nTest content"
    body = BytesIO(content)

    class Client:
        def get_object(self, *, Bucket, Key):
            return {
                "ContentLength": len(content),
                "Body": body,
            }

    storage = object.__new__(S3Storage)
    storage.bucket_name = "test-bucket"
    storage.client = Client()

    result = await storage.download_file(key="test.pdf")

    assert result == content
    assert body.closed


@pytest.mark.anyio
async def test_s3_detects_truncated_download() -> None:
    body = BytesIO(b"short")

    class Client:
        def get_object(self, *, Bucket, Key):
            return {
                "ContentLength": 100,
                "Body": body,
            }

    storage = object.__new__(S3Storage)
    storage.bucket_name = "test-bucket"
    storage.client = Client()

    with pytest.raises(IOError, match="size mismatch"):
        await storage.download_file(key="test.pdf")

    assert body.closed
