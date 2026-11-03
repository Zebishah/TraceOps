import argparse
import asyncio
import getpass
import json
import os

import httpx

from ops_pilot.evaluation.classification import (
    evaluate_incident_classification,
)
from ops_pilot.evaluation.duplicate_payments import (
    evaluate_duplicate_payment_detection,
)
from ops_pilot.evaluation.hitl_safety import (
    evaluate_hitl_safety,
)
from ops_pilot.evaluation.identity import (
    discover_evaluation_organizations,
    evaluation_backend_url,
)
from ops_pilot.evaluation.recommendation import (
    evaluate_recommendation_groundedness,
)
from ops_pilot.evaluation.reporting import (
    build_evaluation_report,
    publish_organization_report,
)
from ops_pilot.evaluation.retrieval import (
    evaluate_document_retrieval,
)
from ops_pilot.evaluation.tool_selection import (
    evaluate_tool_selection,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run scoped OpsPilot quality evaluations.")
    parser.add_argument("--backend-url", default=os.getenv("OPSPILOT_BACKEND_URL"))
    args = parser.parse_args()
    configured_url = args.backend_url or input("Backend root URL: ").strip()
    url = evaluation_backend_url(configured_url)
    email = input("OpsPilot email: ").strip()
    password = getpass.getpass("OpsPilot password (hidden): ")
    async with httpx.AsyncClient(base_url=url, timeout=30, follow_redirects=False) as client:
        organizations = await discover_evaluation_organizations(
            client, email=email, password=password
        )
    del password
    if len(organizations) == 1:
        selected = organizations[0]
    else:
        print("Choose an authorized workspace:")
        for index, organization in enumerate(organizations, start=1):
            print(f"  {index}. {organization.organization_id} ({organization.role})")
        choice = input("Workspace number: ").strip()
        if not choice.isdecimal() or not 1 <= int(choice) <= len(organizations):
            raise ValueError("Choose one of the listed workspace numbers.")
        selected = organizations[int(choice) - 1]
    organization_id = selected.organization_id
    print(f"Evaluation workspace discovered from /auth/me: {organization_id}")

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

    report_path = publish_organization_report(
        organization_id=organization_id,
        report=report,
    )

    print(f"\nEvaluation report written to: {report_path}")

    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
