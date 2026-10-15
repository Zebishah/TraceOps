import asyncio
import json
import os
import uuid
from pathlib import Path

from ops_pilot.evaluation.classification import (
    evaluate_incident_classification,
)
from ops_pilot.evaluation.duplicate_payments import (
    evaluate_duplicate_payment_detection,
)
from ops_pilot.evaluation.hitl_safety import (
    evaluate_hitl_safety,
)
from ops_pilot.evaluation.recommendation import (
    evaluate_recommendation_groundedness,
)
from ops_pilot.evaluation.reporting import (
    build_evaluation_report,
    write_evaluation_report,
)
from ops_pilot.evaluation.retrieval import (
    evaluate_document_retrieval,
)
from ops_pilot.evaluation.tool_selection import (
    evaluate_tool_selection,
)


async def main() -> None:
    organization_id_value = os.getenv("EVALUATION_ORGANIZATION_ID")

    if organization_id_value is None:
        raise RuntimeError("EVALUATION_ORGANIZATION_ID is required")

    organization_id = uuid.UUID(organization_id_value)

    suites = [
        evaluate_duplicate_payment_detection(),
        evaluate_tool_selection(),
        evaluate_hitl_safety(),
        await evaluate_incident_classification(),
        await evaluate_document_retrieval(
            organization_id=organization_id,
        ),
        await evaluate_recommendation_groundedness(),
    ]

    report = build_evaluation_report(
        suites,
    )

    report_json = json.dumps(
        report,
        indent=2,
    )

    print(report_json)

    report_path = Path("evaluation-results/report.json")

    write_evaluation_report(
        report_json=report_json,
        path=report_path,
    )

    print(f"\nEvaluation report written to: {report_path}")

    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
