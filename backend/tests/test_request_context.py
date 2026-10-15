import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ops_pilot.api.request_context import (
    RequestContextMiddleware,
)
from ops_pilot.core.logging import (
    JsonFormatter,
)


def _app() -> FastAPI:
    app = FastAPI()

    app.add_middleware(RequestContextMiddleware)

    @app.get("/test")
    async def test_endpoint() -> dict[str, bool]:
        return {
            "ok": True,
        }

    return app


def test_request_id_is_generated() -> None:
    client = TestClient(_app())

    response = client.get("/test")

    assert response.status_code == 200

    request_id = response.headers.get("x-request-id")

    assert request_id is not None
    assert request_id


def test_existing_request_id_is_preserved() -> None:
    client = TestClient(_app())

    response = client.get(
        "/test",
        headers={
            "X-Request-ID": "req-123",
        },
    )

    assert response.headers["x-request-id"] == "req-123"


def test_invalid_request_id_is_replaced() -> None:
    client = TestClient(_app())

    response = client.get(
        "/test",
        headers={
            "X-Request-ID": "invalid request id !!!",
        },
    )

    assert response.headers["x-request-id"] != "invalid request id !!!"


def test_request_id_is_added_to_logs() -> None:
    formatter = JsonFormatter()

    from ops_pilot.core.request_context import (
        reset_request_id,
        set_request_id,
    )

    token = set_request_id("req-log-123")

    try:
        record = logging.LogRecord(
            name="ops_pilot.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Processing request",
            args=(),
            exc_info=None,
        )

        payload = json.loads(formatter.format(record))

        assert payload["request_id"] == "req-log-123"
    finally:
        reset_request_id(token)
