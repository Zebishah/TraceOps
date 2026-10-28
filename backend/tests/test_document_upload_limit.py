"""D04: upload requests are bounded before body parsing."""

import httpx
import pytest
from fastapi import FastAPI, Request

from ops_pilot.api.upload_limit import (
    MAX_DOCUMENT_UPLOAD_REQUEST_BYTES,
    DocumentUploadLimitMiddleware,
)


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(DocumentUploadLimitMiddleware)

    @app.post("/api/v1/organizations/test-org/documents")
    async def upload(request: Request) -> dict[str, int]:
        data = await request.body()
        return {"size": len(data)}

    return app


@pytest.mark.anyio
async def test_small_upload_passes() -> None:
    transport = httpx.ASGITransport(app=create_test_app())

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/organizations/test-org/documents",
            content=b"small document",
        )

    assert response.status_code == 200
    assert response.json() == {"size": 14}


@pytest.mark.anyio
async def test_oversized_upload_returns_413() -> None:
    transport = httpx.ASGITransport(app=create_test_app())

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/organizations/test-org/documents",
            content=b"x" * (MAX_DOCUMENT_UPLOAD_REQUEST_BYTES + 1),
        )

    assert response.status_code == 413


@pytest.mark.anyio
async def test_other_endpoints_are_unaffected() -> None:
    app = create_test_app()

    @app.post("/other")
    async def other(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/other",
            content=b"hello",
        )

    assert response.status_code == 200
    assert response.json() == {"size": 5}
