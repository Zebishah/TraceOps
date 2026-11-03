import json
import math
import tempfile
import time
import uuid
from pathlib import Path

from ops_pilot.evaluation.models import (
    EvaluationSuiteResult,
)

SUITE_THRESHOLDS: dict[str, float] = {
    "duplicate_payment_detection": 1.0,
    "tool_selection": 1.0,
    "hitl_dangerous_action_safety": 1.0,
    "incident_classification": 0.875,
    "document_retrieval": 1.0,
    "recommendation_groundedness": 1.0,
}


def suite_meets_threshold(
    suite: EvaluationSuiteResult,
) -> bool:
    threshold = SUITE_THRESHOLDS.get(
        suite.suite_name,
        1.0,
    )

    return suite.pass_rate >= threshold


def build_evaluation_report(
    suites: list[EvaluationSuiteResult],
) -> dict[str, object]:
    suite_reports: list[dict[str, object]] = []

    for suite in suites:
        threshold = SUITE_THRESHOLDS.get(
            suite.suite_name,
            1.0,
        )

        meets_threshold = suite_meets_threshold(
            suite,
        )

        suite_reports.append(
            {
                **suite.model_dump(mode="json"),
                "threshold": threshold,
                "meets_threshold": meets_threshold,
            }
        )

    passed = all(suite_meets_threshold(suite) for suite in suites)

    return {
        "passed": passed,
        "total_suites": len(suites),
        "passed_suites": sum(suite_meets_threshold(suite) for suite in suites),
        "failed_suites": sum(not suite_meets_threshold(suite) for suite in suites),
        "suites": suite_reports,
    }


def write_evaluation_report(
    *,
    report_json: str,
    path: Path,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        report_json,
        encoding="utf-8",
    )


MAX_REPORT_BYTES = 2_000_000


def organization_report_path(organization_id: uuid.UUID) -> Path:
    return Path("evaluation-results") / str(organization_id) / "report.json"


def publish_organization_report(*, organization_id: uuid.UUID, report: dict[str, object]) -> Path:
    """Bind results to the verified membership that supplied the retrieval scope."""
    path = organization_report_path(organization_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "organization_id": str(organization_id),
            "generated_at": time.time(),
            "report": report,
        },
        indent=2,
        allow_nan=False,
    ).encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError("Evaluation report exceeds the supported size limit")
    # Readers must never observe a half-written report.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def load_organization_report(organization_id: uuid.UUID) -> dict[str, object]:
    path = organization_report_path(organization_id)
    with path.open("rb") as handle:
        data = handle.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("Evaluation report exceeds the supported size limit")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise ValueError("Evaluation report has an invalid format") from None
    if not isinstance(value, dict):
        raise ValueError("Evaluation report has an invalid format")
    if value.get("organization_id") != str(organization_id):
        # Even a misplaced file cannot expose a different workspace's results.
        raise FileNotFoundError("No report is published for this organization")
    report = value.get("report")
    generated_at = value.get("generated_at")
    if (
        not isinstance(report, dict)
        or isinstance(generated_at, bool)
        or not isinstance(generated_at, (int, float))
        or not math.isfinite(generated_at)
        or generated_at <= 0
    ):
        raise ValueError("Evaluation report has an invalid format")
    return {"report": report, "generated_at": generated_at}
