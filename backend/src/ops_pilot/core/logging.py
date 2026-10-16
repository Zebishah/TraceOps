import json
import logging
from datetime import UTC, datetime
from typing import Any

from ops_pilot.core.request_context import (
    get_request_id,
)


class JsonFormatter(logging.Formatter):
    def format(
        self,
        record: logging.LogRecord,
    ) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = (
            getattr(
                record,
                "request_id",
                None,
            )
            or get_request_id()
        )

        if request_id is not None:
            payload["request_id"] = str(request_id)
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)

        for key in (
            "organization_id",
            "incident_id",
            "workflow_thread_id",
            "provider",
            "model",
            "operation",
            "node",
            "tool_name",
            "tool_call_id",
            "success",
            "status_code",
            "attempt",
            "duration_ms",
            "webhook_path",
        ):
            value = getattr(
                record,
                key,
                None,
            )

            if value is not None:
                payload[key] = str(value)

        return json.dumps(
            payload,
            ensure_ascii=False,
        )


def configure_logging(
    *,
    level: str,
) -> None:
    root_logger = logging.getLogger()

    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger.addHandler(handler)

    root_logger.setLevel(level.upper())
