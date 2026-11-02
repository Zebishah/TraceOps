import json
import logging

from ops_pilot.core.logging import JsonFormatter


def test_formatter_preserves_recovery_identifiers_and_counters() -> None:
    record = logging.makeLogRecord(
        {
            "name": "ops_pilot.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "incident_analysis_retry_requested",
            "job_id": "test-job",
            "dispatch_id": "new-dispatch",
            "previous_dispatch_id": "old-dispatch",
            "requested_by_user_id": "reviewer",
            "duration_ms": 125.5,
            "claimed": 3,
            "failed": 0,
            "quarantined_backlog": 1,
            "authorization": "must-not-be-logged",
        }
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["job_id"] == "test-job"
    assert payload["dispatch_id"] == "new-dispatch"
    assert payload["previous_dispatch_id"] == "old-dispatch"
    assert payload["requested_by_user_id"] == "reviewer"
    assert payload["duration_ms"] == "125.5"
    assert payload["claimed"] == "3"
    assert payload["failed"] == "0"
    assert payload["quarantined_backlog"] == "1"
    assert "authorization" not in payload
