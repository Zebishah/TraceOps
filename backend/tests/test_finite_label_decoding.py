"""Finite label syntax, legacy artifact compatibility and immutable conversion."""

import json

import pytest

from finetuning import constrain_classifier
from finetuning.artifacts import verify_artifact
from finetuning.label_decoding import CATEGORIES, PRIORITIES, FiniteLabelDecoder
from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.finetuning.quality import canonical_hash
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory
from tests.finetuning_helpers import fake_artifact


class ByteTokenizer:
    eos_token_id = 0

    def encode(self, text, *, add_special_tokens=False):
        return [ord(character) + 1 for character in text]

    def decode(self, token_ids, *, skip_special_tokens=False):
        return "".join(chr(token - 1) for token in token_ids if token)


def test_all_32_canonical_labels_are_allowed_and_eos_requires_a_complete_answer():
    tokenizer = ByteTokenizer()
    decoder = FiniteLabelDecoder(tokenizer, max_new_tokens=64)
    assert set(CATEGORIES) == {str(value) for value in IncidentCategory}
    assert set(PRIORITIES) == {str(value) for value in IncidentPriority}
    for category in CATEGORIES:
        for priority in PRIORITIES:
            answer = ClassifierLabels(category=category, priority=priority).model_dump_json()
            tokens = tokenizer.encode(answer)
            for length, token in enumerate(tokens):
                allowed = decoder.allowed_tokens(tokens[:length])
                assert token in allowed
                assert tokenizer.eos_token_id not in allowed
            assert decoder.allowed_tokens(tokens) == [tokenizer.eos_token_id]


@pytest.mark.parametrize(
    "invalid",
    [
        '{"category":"storage","priority":"high"}',
        '{"category":"payment","priority":"urgent"}',
        "Here is the answer:",
        '{"category":"system","priority":"low","confidence":1}',
        '{"category":"system","priority":"low"} trailing explanation',
    ],
)
def test_unsupported_category_priority_fields_and_prose_are_not_valid_token_paths(invalid):
    tokenizer = ByteTokenizer()
    decoder = FiniteLabelDecoder(tokenizer, max_new_tokens=64)
    with pytest.raises(ValueError, match="vocabulary"):
        decoder.allowed_tokens(tokenizer.encode(invalid))


def test_budget_and_tokenizer_integrity_are_checked_before_generation():
    with pytest.raises(ValueError, match="budget"):
        FiniteLabelDecoder(ByteTokenizer(), max_new_tokens=16)

    class MissingEOS(ByteTokenizer):
        eos_token_id = None

    with pytest.raises(ValueError, match="EOS"):
        FiniteLabelDecoder(MissingEOS(), max_new_tokens=64)

    class BrokenDecode(ByteTokenizer):
        def decode(self, token_ids, *, skip_special_tokens=False):
            return "different text"

    with pytest.raises(ValueError, match="round-trip"):
        FiniteLabelDecoder(BrokenDecode(), max_new_tokens=64)


def test_old_manifest_fingerprint_is_preserved_exactly(tmp_path):
    path = tmp_path / "legacy"
    artifact = fake_artifact(path)
    payload = artifact.model_dump(mode="json")
    payload.pop("output_policy")
    payload.pop("derived_from_artifact_sha256")
    manifest = path / "artifact_manifest.json"
    manifest.write_text(json.dumps(payload))
    restored = verify_artifact(path)
    assert restored.output_policy is None
    assert restored.fingerprint() == canonical_hash(payload)


def test_conversion_changes_identity_without_changing_original_files_or_weights(
    tmp_path, monkeypatch
):
    source = tmp_path / "original"
    artifact = fake_artifact(source)
    original_files = {p.name: p.read_bytes() for p in source.iterdir()}

    def validate(path, budget):
        assert path == source
        FiniteLabelDecoder(ByteTokenizer(), max_new_tokens=budget)

    monkeypatch.setattr(constrain_classifier, "validate_tokenizer", validate)
    destination = tmp_path / "constrained"
    parent, current = constrain_classifier.constrain_artifact(source, destination)
    derived = verify_artifact(destination)
    assert parent == artifact.fingerprint() and current != parent
    assert derived.output_policy == "finite-labels-v1"
    assert derived.derived_from_artifact_sha256 == parent
    assert derived.files == artifact.files
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original_files
    assert (destination / "adapter_model.safetensors").read_bytes() == original_files[
        "adapter_model.safetensors"
    ]
    with pytest.raises(ValueError, match="must not exist"):
        constrain_classifier.constrain_artifact(source, destination)
    with pytest.raises(ValueError, match="already"):
        constrain_classifier.constrain_artifact(destination, tmp_path / "another")


def test_invalid_tokenizer_does_not_create_destination(tmp_path, monkeypatch):
    source = tmp_path / "original"
    fake_artifact(source)

    def invalid(path, budget):
        raise ValueError("Tokenizer cannot round-trip")

    monkeypatch.setattr(constrain_classifier, "validate_tokenizer", invalid)
    destination = tmp_path / "constrained"
    with pytest.raises(ValueError, match="round-trip"):
        constrain_classifier.constrain_artifact(source, destination)
    assert not destination.exists()
