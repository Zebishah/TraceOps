import json
import logging

from ops_pilot.core.logging import JsonFormatter
from ops_pilot.core.request_context import (
    reset_request_id,
    set_request_id,
)


def test_structured_log_combines_request_and_operation_context() -> None:
    formatter = JsonFormatter()

    token = set_request_id("req-observability-123")

    try:
        record = logging.LogRecord(
            name="ops_pilot.observability",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="external_call_succeeded",
            args=(),
            exc_info=None,
        )

        record.provider = "mistral"
        record.model = "mistral-embed"
        record.operation = "embeddings"
        record.status_code = 200
        record.attempt = 1
        record.duration_ms = 42.5

        payload = json.loads(formatter.format(record))

        assert payload["request_id"] == "req-observability-123"
        assert payload["provider"] == "mistral"
        assert payload["model"] == "mistral-embed"
        assert payload["operation"] == "embeddings"
        assert payload["status_code"] == "200"
        assert payload["attempt"] == "1"
        assert payload["duration_ms"] == "42.5"

    finally:
        reset_request_id(token)


def test_structured_logging_does_not_emit_unapproved_sensitive_fields() -> None:
    formatter = JsonFormatter()

    record = logging.LogRecord(
        name="ops_pilot.security",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="provider_call",
        args=(),
        exc_info=None,
    )

    record.api_key = "super-secret-api-key"
    record.authorization = "Bearer secret-token"
    record.password = "secret-password"

    payload = json.loads(formatter.format(record))

    serialized = json.dumps(payload)

    assert "super-secret-api-key" not in serialized
    assert "Bearer secret-token" not in serialized
    assert "secret-password" not in serialized

    assert "api_key" not in payload
    assert "authorization" not in payload
    assert "password" not in payload
