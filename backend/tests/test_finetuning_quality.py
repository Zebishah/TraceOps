from datetime import UTC, datetime

import pytest

from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.finetuning.quality import PromotionPolicy, promotion_failures, summarize_cases
from tests.finetuning_helpers import report, review, small_policy, valid_cases


def test_metrics_count_invalid_and_critical_downgrades():
    cases = valid_cases()
    cases[3] = cases[3].model_copy(
        update={"predicted": ClassifierLabels(category=cases[3].expected.category, priority="low")}
    )
    cases[0] = cases[0].model_copy(update={"predicted": None, "error": "invalid_output"})
    metrics = summarize_cases(cases)
    assert metrics["joint_accuracy"] == 6 / 8
    assert metrics["category_accuracy"] == 7 / 8
    assert metrics["critical_misses"] == 1
    assert metrics["high_risk_downgrades"] == 1
    assert metrics["invalid_outputs"] == 1
    assert metrics["category"]["confusion_matrix"]["payment"]["invalid"] == 1
    assert metrics["category"]["per_class"]["payment"]["recall"] == 0


def test_paired_perfect_reports_pass_explicit_unit_test_policy():
    assert promotion_failures(report(), report("groq"), review(), small_policy()) == []


def test_default_policy_rejects_tiny_evaluation():
    failures = promotion_failures(report(), report("groq"), review(), PromotionPolicy())
    assert "Insufficient held-out examples" in failures
    assert any("Insufficient category coverage" in failure for failure in failures)


@pytest.mark.parametrize("source", ["synthetic", "unreviewed"])
def test_unreviewed_or_synthetic_data_cannot_be_promoted(source):
    assert "Real reviewed, de-identified incidents are required" in promotion_failures(
        report(), report("groq"), review(source), small_policy()
    )


def test_reports_must_use_identical_cases_and_test_split():
    baseline = report("groq")
    baseline.split = "validation"
    baseline.cases = baseline.cases[:-1]
    failures = promotion_failures(report(), baseline, review(), small_policy())
    assert "Promotion requires held-out test reports" in failures
    assert "Reports must contain identical cases and expected labels" in failures


def test_infrastructure_failures_block_promotion():
    candidate = report()
    candidate.cases[0] = candidate.cases[0].model_copy(
        update={"predicted": None, "error": "infrastructure"}
    )
    failures = promotion_failures(candidate, report("groq"), review(), small_policy())
    assert "Infrastructure failures invalidate promotion evidence" in failures


def test_no_critical_miss_can_be_hidden_by_average_accuracy():
    candidate = report()
    candidate.cases[3].predicted = ClassifierLabels(category="data", priority="high")
    failures = promotion_failures(candidate, report("groq"), review(), small_policy())
    assert "Critical incidents were missed" in failures
    assert "High-risk downgrades regress against Groq" in failures


def test_duplicate_cases_and_nonfinite_latency_rejected():
    with pytest.raises(ValueError, match="unique"):
        summarize_cases([valid_cases()[0], valid_cases()[0]])
    with pytest.raises(ValueError):
        valid_cases()[0].model_validate(
            {**valid_cases()[0].model_dump(), "latency_seconds": float("nan")}
        )


def test_review_requires_timezone():
    with pytest.raises(ValueError, match="timezone"):
        review().model_validate(
            {**review().model_dump(), "reviewed_at": datetime.now(UTC).replace(tzinfo=None)}
        )


def test_paraphrases_do_not_inflate_independent_test_coverage():
    candidate = report()
    baseline = report("groq")
    for case in [*candidate.cases, *baseline.cases]:
        case.group_id = "f" * 64
    failures = promotion_failures(candidate, baseline, review(), small_policy())
    assert "Insufficient independent held-out incident groups" in failures


def test_wrong_category_on_critical_incident_is_also_a_miss():
    cases = valid_cases()
    cases[3].predicted = ClassifierLabels(category="other", priority="critical")
    assert summarize_cases(cases)["critical_misses"] == 1
