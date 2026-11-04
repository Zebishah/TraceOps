"""Artificial, signed unit-test fixtures; never production evaluation evidence."""

from datetime import UTC, datetime

from finetuning.artifacts import LoadingSpec, ModelReference, write_artifact
from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.finetuning.quality import (
    DatasetReview,
    EvaluationCase,
    EvaluationReport,
    PromotionPolicy,
    canonical_hash,
    expected_case_map,
)
from ops_pilot.schemas.incident_classification import IncidentCategory


def valid_cases():
    result = []
    for index, category in enumerate(IncidentCategory):
        labels = ClassifierLabels(
            category=category, priority=["low", "medium", "high", "critical"][index % 4]
        )
        result.append(
            EvaluationCase(
                case_id=canonical_hash({"unit-test": index}),
                group_id=canonical_hash({"unit-group": index}),
                expected=labels,
                predicted=labels,
                latency_seconds=0.05,
            )
        )
    return result


def fake_artifact(path):
    path.mkdir(parents=True)
    (path / "adapter_config.json").write_text('{"base_model_name_or_path":"unit/model"}')
    (path / "adapter_model.safetensors").write_bytes(b"UNIT-TEST-NOT-A-REAL-MODEL")
    (path / "tokenizer_config.json").write_text("{}")
    import hashlib

    from ops_pilot.finetuning.dataset import CLASSIFIER_SYSTEM_PROMPT

    return write_artifact(
        path,
        base=ModelReference(model_id="unit/model", revision="1" * 40),
        tokenizer_revision="1" * 40,
        loading=LoadingSpec(),
        prompt_sha256=hashlib.sha256(CLASSIFIER_SYSTEM_PROMPT.encode()).hexdigest(),
        dataset_sha256="a" * 64,
        train_sha256="c" * 64,
        validation_sha256="d" * 64,
        test_sha256="b" * 64,
        test_cases_sha256=canonical_hash(expected_case_map(valid_cases())),
        max_input_tokens=512,
        training={"optimizer_steps": 1},
    )


def report(backend="adapter", artifact_sha256="e" * 64):
    return EvaluationReport(
        backend=backend,
        split="test",
        dataset_sha256="a" * 64,
        input_sha256="b" * 64,
        artifact_sha256=artifact_sha256 if backend == "adapter" else None,
        model="unit/model",
        model_revision="1" * 40,
        created_at=datetime.now(UTC),
        peak_rss_mib=100,
        cases=valid_cases(),
    )


def review(source="reviewed_incidents"):
    return DatasetReview(
        dataset_sha256="a" * 64,
        source=source,
        reviewer="unit-test-reviewer",
        reviewed_at=datetime.now(UTC),
        labels_approved=True,
        deidentified=True,
    )


def small_policy():
    return PromotionPolicy(
        min_test_examples=8,
        min_test_groups=8,
        min_category_examples=1,
        min_priority_examples=1,
        min_critical_examples=1,
        min_joint_accuracy=1,
        min_macro_f1=1,
    )
