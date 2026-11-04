import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from finetuning.artifacts import ModelReference, verify_artifact
from finetuning.release import approve_release, verify_release
from tests.finetuning_helpers import fake_artifact, report, review, small_policy


@pytest.fixture
def evidence(tmp_path):
    adapter = tmp_path / "adapter"
    artifact = fake_artifact(adapter)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(report(artifact_sha256=artifact.fingerprint()).model_dump_json())
    baseline = tmp_path / "baseline.json"
    baseline.write_text(report("groq").model_dump_json())
    reviewed = tmp_path / "review.json"
    reviewed.write_text(review().model_dump_json())
    return adapter, candidate, baseline, reviewed


def approve(evidence, tmp_path, key):
    adapter, candidate, baseline, reviewed = evidence
    output = tmp_path / "release.json"
    identity = approve_release(
        adapter_path=adapter,
        adapter_report=candidate,
        baseline_report=baseline,
        review_path=reviewed,
        private_key=key.private_bytes_raw(),
        output=output,
        policy=small_policy(),
    )
    return output, identity


def test_release_signature_and_artifact_binding(evidence, tmp_path):
    key = Ed25519PrivateKey.generate()
    output, identity = approve(evidence, tmp_path, key)
    assert verify_release(evidence[0], output, key.public_key().public_bytes_raw()) == identity
    wrong = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="signature"):
        verify_release(evidence[0], output, wrong.public_key().public_bytes_raw())
    payload = json.loads(output.read_text())
    payload["payload"]["reviewer"] = "tampered"
    output.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="signature"):
        verify_release(evidence[0], output, key.public_key().public_bytes_raw())


def test_modified_adapter_and_path_traversal_rejected(evidence):
    adapter = evidence[0]
    (adapter / "adapter_model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="modified"):
        verify_artifact(adapter)
    payload = json.loads((adapter / "artifact_manifest.json").read_text())
    payload["files"]["../outside"] = "0" * 64
    (adapter / "artifact_manifest.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="file entry"):
        verify_artifact(adapter)


def test_synthetic_evidence_and_changed_holdout_cannot_be_signed(evidence, tmp_path):
    key = Ed25519PrivateKey.generate()
    evidence[3].write_text(review("synthetic").model_dump_json())
    with pytest.raises(ValueError, match="reviewed"):
        approve(evidence, tmp_path, key)
    evidence[3].write_text(review().model_dump_json())
    candidate = report(artifact_sha256=verify_artifact(evidence[0]).fingerprint())
    candidate.input_sha256 = "f" * 64
    evidence[1].write_text(candidate.model_dump_json())
    with pytest.raises(ValueError, match="held-out test file"):
        approve(evidence, tmp_path, key)


def test_future_review_and_unpinned_models_rejected(evidence, tmp_path):
    reviewed = review()
    reviewed.reviewed_at = datetime.now(UTC) + timedelta(days=1)
    evidence[3].write_text(reviewed.model_dump_json())
    with pytest.raises(ValueError, match="future"):
        approve(evidence, tmp_path, Ed25519PrivateKey.generate())
    with pytest.raises(ValueError, match="pinned"):
        ModelReference(model_id="unit/model")
    with pytest.raises(ValueError):
        ModelReference(model_id="unit/model", revision="main")


def test_packaging_excludes_optimizer_and_unlisted_files(evidence, tmp_path):
    from finetuning.artifacts import export_artifact

    source = evidence[0]
    (source / "optimizer.pt").write_bytes(b"private training state")
    (source / "checkpoints").mkdir()
    destination = tmp_path / "inference-only"
    artifact = export_artifact(source, destination)
    assert artifact.fingerprint() == verify_artifact(source).fingerprint()
    assert not (destination / "optimizer.pt").exists()
    assert not (destination / "checkpoints").exists()
    with pytest.raises(ValueError, match="must not exist"):
        export_artifact(source, destination)


def test_old_release_does_not_authorize_a_changed_decoding_policy(evidence, tmp_path, monkeypatch):
    from finetuning import constrain_classifier
    from finetuning.label_decoding import FiniteLabelDecoder
    from tests.test_finite_label_decoding import ByteTokenizer

    key = Ed25519PrivateKey.generate()
    release_path, identity = approve(evidence, tmp_path, key)
    assert (
        verify_release(evidence[0], release_path, key.public_key().public_bytes_raw()) == identity
    )

    def validate(path, budget):
        FiniteLabelDecoder(ByteTokenizer(), max_new_tokens=budget)

    monkeypatch.setattr(constrain_classifier, "validate_tokenizer", validate)
    destination = tmp_path / "different-policy"
    constrain_classifier.constrain_artifact(evidence[0], destination)
    with pytest.raises(ValueError, match="does not authorize"):
        verify_release(destination, release_path, key.public_key().public_bytes_raw())
