"""Offline classification metrics and fail-closed promotion policy; no ML imports."""

import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class DatasetReview(StrictRecord):
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: Literal["reviewed_incidents", "synthetic", "unreviewed"]
    reviewer: str = Field(min_length=3, max_length=120)
    reviewed_at: datetime
    labels_approved: bool
    deidentified: bool

    @model_validator(mode="after")
    def timezone_required(self) -> "DatasetReview":
        if self.reviewed_at.tzinfo is None:
            raise ValueError("Review timestamp must include a timezone")
        return self


class EvaluationCase(StrictRecord):
    case_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    group_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected: ClassifierLabels
    predicted: ClassifierLabels | None = None
    error: Literal["invalid_output", "infrastructure"] | None = None
    latency_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def one_result(self) -> "EvaluationCase":
        if (self.predicted is None) != (self.error is not None):
            raise ValueError("Case must contain either a prediction or an error")
        return self


class ClassMetrics(TypedDict):
    support: int
    precision: float
    recall: float
    f1: float


class LabelMetrics(TypedDict):
    confusion_matrix: dict[str, dict[str, int]]
    per_class: dict[str, ClassMetrics]
    macro_f1: float


class SummaryMetrics(TypedDict):
    total: int
    independent_groups: int
    category_accuracy: float
    priority_accuracy: float
    joint_accuracy: float
    invalid_outputs: int
    infrastructure_errors: int
    critical_misses: int
    high_risk_downgrades: int
    latency_p50_seconds: float
    latency_p95_seconds: float
    category: LabelMetrics
    priority: LabelMetrics


def _label_metrics(cases: list[EvaluationCase], field: str, labels: list[str]) -> LabelMetrics:
    confusion = {actual: {predicted: 0 for predicted in [*labels, "invalid"]} for actual in labels}
    for case in cases:
        actual = str(getattr(case.expected, field))
        predicted = str(getattr(case.predicted, field)) if case.predicted else "invalid"
        confusion[actual][predicted] += 1
    per_class: dict[str, ClassMetrics] = {}
    for label in labels:
        true_positive = confusion[label][label]
        support = sum(confusion[label].values())
        predicted_count = sum(row[label] for row in confusion.values())
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
    return {
        "confusion_matrix": confusion,
        "per_class": per_class,
        "macro_f1": sum(row["f1"] for row in per_class.values()) / len(labels),
    }


def summarize_cases(cases: list[EvaluationCase]) -> SummaryMetrics:
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Evaluation requires nonempty, unique cases")
    total = len(cases)
    category_correct = priority_correct = joint_correct = 0
    severity = {
        str(value): index for index, value in enumerate(["low", "medium", "high", "critical"])
    }
    critical_misses = high_risk_downgrades = 0
    for case in cases:
        predicted = case.predicted
        category_ok = predicted is not None and predicted.category == case.expected.category
        priority_ok = predicted is not None and predicted.priority == case.expected.priority
        category_correct += category_ok
        priority_correct += priority_ok
        joint_correct += category_ok and priority_ok
        if case.expected.priority == "critical" and not (category_ok and priority_ok):
            critical_misses += 1
        if case.expected.priority in {"high", "critical"} and (
            predicted is None
            or severity[str(predicted.priority)] < severity[str(case.expected.priority)]
        ):
            high_risk_downgrades += 1
    latencies = sorted(case.latency_seconds for case in cases)
    errors = Counter(case.error for case in cases if case.error)
    return {
        "total": total,
        "independent_groups": len({case.group_id for case in cases}),
        "category_accuracy": category_correct / total,
        "priority_accuracy": priority_correct / total,
        "joint_accuracy": joint_correct / total,
        "invalid_outputs": errors["invalid_output"],
        "infrastructure_errors": errors["infrastructure"],
        "critical_misses": critical_misses,
        "high_risk_downgrades": high_risk_downgrades,
        "latency_p50_seconds": latencies[math.ceil(0.50 * total) - 1],
        "latency_p95_seconds": latencies[math.ceil(0.95 * total) - 1],
        "category": _label_metrics(cases, "category", [str(v) for v in IncidentCategory]),
        "priority": _label_metrics(cases, "priority", [str(v) for v in IncidentPriority]),
    }


class EvaluationReport(StrictRecord):
    schema_version: Literal[1] = 1
    backend: Literal["groq", "adapter", "base"]
    split: Literal["validation", "test"]
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    model: str
    model_revision: str | None = None
    created_at: datetime
    peak_rss_mib: float = Field(ge=0)
    cases: list[EvaluationCase] = Field(min_length=1)

    def metrics(self) -> SummaryMetrics:
        return summarize_cases(self.cases)


class PromotionPolicy(StrictRecord):
    """Versioned defaults; policy changes require a new signed release."""

    min_test_examples: int = Field(default=200, ge=1)
    min_test_groups: int = Field(default=200, ge=1)
    min_category_examples: int = Field(default=10, ge=1)
    min_priority_examples: int = Field(default=10, ge=1)
    min_critical_examples: int = Field(default=20, ge=1)
    min_joint_accuracy: float = Field(default=0.90, ge=0, le=1)
    min_macro_f1: float = Field(default=0.85, ge=0, le=1)
    max_category_recall_regression: float = Field(default=0.05, ge=0, le=1)
    max_invalid_rate: float = Field(default=0.01, ge=0, le=1)
    max_p95_seconds: float = Field(default=8, gt=0)
    max_peak_rss_mib: float = Field(default=6144, gt=0)
    max_joint_regression: float = Field(default=0, ge=0, le=1)


def promotion_failures(
    adapter: EvaluationReport,
    baseline: EvaluationReport,
    review: DatasetReview,
    policy: PromotionPolicy,
) -> list[str]:
    failures = []
    if adapter.backend != "adapter" or baseline.backend != "groq":
        failures.append("Require adapter and Groq baseline reports")
    if adapter.split != "test" or baseline.split != "test":
        failures.append("Promotion requires held-out test reports")
    if not adapter.artifact_sha256:
        failures.append("Adapter report is not bound to an artifact")
    if (
        adapter.dataset_sha256 != baseline.dataset_sha256
        or adapter.input_sha256 != baseline.input_sha256
    ):
        failures.append("Reports must use the same dataset and test input")
    expected_adapter = expected_case_map(adapter.cases)
    expected_baseline = expected_case_map(baseline.cases)
    if expected_adapter != expected_baseline:
        failures.append("Reports must contain identical cases and expected labels")
    if review.dataset_sha256 != adapter.dataset_sha256:
        failures.append("Review does not match the evaluated dataset")
    if (
        review.source != "reviewed_incidents"
        or not review.labels_approved
        or not review.deidentified
    ):
        failures.append("Real reviewed, de-identified incidents are required")
    metrics, reference = adapter.metrics(), baseline.metrics()
    if metrics["total"] < policy.min_test_examples:
        failures.append("Insufficient held-out examples")
    if metrics["independent_groups"] < policy.min_test_groups:
        failures.append("Insufficient independent held-out incident groups")
    for label, row in metrics["category"]["per_class"].items():
        if row["support"] < policy.min_category_examples:
            failures.append(f"Insufficient category coverage: {label}")
    for label, row in metrics["priority"]["per_class"].items():
        minimum = (
            policy.min_critical_examples if label == "critical" else policy.min_priority_examples
        )
        if row["support"] < minimum:
            failures.append(f"Insufficient priority coverage: {label}")
    if metrics["joint_accuracy"] < policy.min_joint_accuracy:
        failures.append("Joint accuracy below policy")
    if min(metrics["category"]["macro_f1"], metrics["priority"]["macro_f1"]) < policy.min_macro_f1:
        failures.append("Macro F1 below policy")
    for label, row in metrics["category"]["per_class"].items():
        reference_recall = reference["category"]["per_class"][label]["recall"]
        if row["recall"] + policy.max_category_recall_regression < reference_recall:
            failures.append(f"Category recall regresses against Groq: {label}")
    if metrics["joint_accuracy"] + policy.max_joint_regression < reference["joint_accuracy"]:
        failures.append("Joint accuracy regresses against Groq")
    if metrics["high_risk_downgrades"] > reference["high_risk_downgrades"]:
        failures.append("High-risk downgrades regress against Groq")
    if metrics["critical_misses"]:
        failures.append("Critical incidents were missed")
    if metrics["invalid_outputs"] / metrics["total"] > policy.max_invalid_rate:
        failures.append("Invalid output rate exceeds policy")
    if metrics["infrastructure_errors"] or reference["infrastructure_errors"]:
        failures.append("Infrastructure failures invalidate promotion evidence")
    if metrics["latency_p95_seconds"] > policy.max_p95_seconds:
        failures.append("P95 latency exceeds policy")
    if adapter.peak_rss_mib > policy.max_peak_rss_mib:
        failures.append("Peak memory exceeds policy")
    return failures


def expected_case_map(cases: list[EvaluationCase]) -> dict[str, object]:
    return {
        case.case_id: {"expected": case.expected.model_dump(mode="json"), "group_id": case.group_id}
        for case in cases
    }
