from ops_pilot.evaluation.models import (
    EvaluationCaseResult,
    EvaluationStatus,
    EvaluationSuiteResult,
)
from ops_pilot.evaluation.reporting import (
    build_evaluation_report,
    suite_meets_threshold,
)


def _suite(
    *,
    name: str,
    pass_rate: float,
) -> EvaluationSuiteResult:
    total_cases = 8
    passed_cases = round(total_cases * pass_rate)

    return EvaluationSuiteResult(
        suite_name=name,
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=(total_cases - passed_cases),
        pass_rate=pass_rate,
        cases=[
            EvaluationCaseResult(
                case_id="case",
                status=EvaluationStatus.PASSED,
                checks=[],
            )
        ],
    )


def test_safety_suite_requires_perfect_score() -> None:
    suite = _suite(
        name="hitl_dangerous_action_safety",
        pass_rate=0.99,
    )

    assert suite_meets_threshold(suite) is False


def test_classification_threshold_allows_seven_of_eight() -> None:
    suite = _suite(
        name="incident_classification",
        pass_rate=0.875,
    )

    assert suite_meets_threshold(suite) is True


def test_report_fails_when_suite_below_threshold() -> None:
    suites = [
        _suite(
            name="duplicate_payment_detection",
            pass_rate=1.0,
        ),
        _suite(
            name="tool_selection",
            pass_rate=0.5,
        ),
    ]

    report = build_evaluation_report(suites)

    assert report["passed"] is False
    assert report["total_suites"] == 2
    assert report["failed_suites"] == 1


def test_report_is_published_and_loaded_for_its_verified_organization(tmp_path, monkeypatch):
    import json
    import uuid

    from ops_pilot.evaluation.reporting import load_organization_report, publish_organization_report

    monkeypatch.chdir(tmp_path)
    organization_id = uuid.uuid4()
    report = {"passed": True, "total_suites": 1, "suites": []}
    path = publish_organization_report(organization_id=organization_id, report=report)
    assert path.parts == ("evaluation-results", str(organization_id), "report.json")
    assert json.loads(path.read_text())["organization_id"] == str(organization_id)
    assert load_organization_report(organization_id)["report"] == report
    assert load_organization_report(organization_id)["generated_at"] > 0


def test_legacy_or_foreign_report_is_never_assigned_to_current_workspace(tmp_path, monkeypatch):
    import uuid

    import pytest

    from ops_pilot.evaluation.reporting import (
        load_organization_report,
        organization_report_path,
        publish_organization_report,
    )

    monkeypatch.chdir(tmp_path)
    organization_id, other_id = uuid.uuid4(), uuid.uuid4()
    other_path = publish_organization_report(
        organization_id=other_id, report={"private_marker": "other-workspace"}
    )
    # A global legacy file has no proven ownership and must not become a fallback.
    (tmp_path / "evaluation-results" / "report.json").write_text(other_path.read_text())
    with pytest.raises(FileNotFoundError):
        load_organization_report(organization_id)
    wrong_path = organization_report_path(organization_id)
    wrong_path.parent.mkdir(parents=True)
    wrong_path.write_text(other_path.read_text())
    with pytest.raises(FileNotFoundError):
        load_organization_report(organization_id)


def test_invalid_or_oversized_report_is_rejected(tmp_path, monkeypatch):
    import uuid

    import pytest

    from ops_pilot.evaluation.reporting import (
        MAX_REPORT_BYTES,
        load_organization_report,
        organization_report_path,
    )

    monkeypatch.chdir(tmp_path)
    organization_id = uuid.uuid4()
    path = organization_report_path(organization_id)
    path.parent.mkdir(parents=True)
    for content in [b"not-json", b"[]", b"x" * (MAX_REPORT_BYTES + 1)]:
        path.write_bytes(content)
        with pytest.raises(ValueError):
            load_organization_report(organization_id)


def test_failed_oversized_publication_preserves_previous_report(tmp_path, monkeypatch):
    import uuid

    import pytest

    from ops_pilot.evaluation.reporting import (
        MAX_REPORT_BYTES,
        load_organization_report,
        publish_organization_report,
    )

    monkeypatch.chdir(tmp_path)
    organization_id = uuid.uuid4()
    publish_organization_report(organization_id=organization_id, report={"passed": True})
    with pytest.raises(ValueError):
        publish_organization_report(
            organization_id=organization_id, report={"text": "x" * MAX_REPORT_BYTES}
        )
    assert load_organization_report(organization_id)["report"] == {"passed": True}
