import json
import logging

from ops_pilot.core.logging import (
    JsonFormatter,
    configure_logging,
)


def test_json_formatter_outputs_structured_log() -> None:
    formatter = JsonFormatter()

    record = logging.LogRecord(
        name="ops_pilot.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Incident investigation started",
        args=(),
        exc_info=None,
    )

    record.request_id = "req-123"
    record.organization_id = "org-123"
    record.incident_id = "inc-123"

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "ops_pilot.test"
    assert payload["message"] == "Incident investigation started"
    assert payload["request_id"] == "req-123"
    assert payload["organization_id"] == "org-123"
    assert payload["incident_id"] == "inc-123"
    assert "timestamp" in payload


def test_configure_logging_sets_root_level() -> None:
    configure_logging(
        level="DEBUG",
    )

    root_logger = logging.getLogger()

    assert root_logger.level == logging.DEBUG
    assert len(root_logger.handlers) == 1
    assert isinstance(
        root_logger.handlers[0].formatter,
        JsonFormatter,
    )
