"""Pinned model references, shared loading settings and checksummed adapter artifacts."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ops_pilot.finetuning.dataset import CLASSIFIER_SYSTEM_PROMPT
from ops_pilot.finetuning.quality import StrictRecord, canonical_hash

ARTIFACT_FILE = "artifact_manifest.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def local_model_hash(path: Path) -> str:
    files = {
        file.name: file_sha256(file)
        for file in sorted(path.iterdir())
        if file.is_file()
        and not file.is_symlink()
        and file.suffix in {".json", ".safetensors", ".model", ".txt", ".jinja"}
    }
    if not files or not any(name.endswith(".safetensors") for name in files):
        raise ValueError("Local base model must contain safetensors weights")
    return canonical_hash(files)


class ModelReference(StrictRecord):
    model_id: str = Field(min_length=1)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    local_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def pinned(self):
        if (self.revision is None) == (self.local_sha256 is None):
            raise ValueError("Model requires exactly one pinned revision or local fingerprint")
        return self


def resolve_reference(model_id: str, revision: str | None = None) -> ModelReference:
    local = Path(model_id)
    if local.is_dir():
        if revision:
            raise ValueError("Local models use content fingerprints, not Hub revisions")
        return ModelReference(model_id=str(local.resolve()), local_sha256=local_model_hash(local))
    if revision and not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Revision must be a full Hub commit SHA")
    if revision:
        return ModelReference(model_id=model_id, revision=revision)
    from huggingface_hub import model_info

    resolved = model_info(model_id, revision=revision).sha
    return ModelReference(model_id=model_id, revision=resolved)


class LoadingSpec(StrictRecord):
    quantization: Literal["none", "nf4"] = "none"
    compute_dtype: Literal["float32"] = "float32"
    double_quantization: bool = False


def load_base(reference: ModelReference, spec: LoadingSpec, *, device: str):
    import torch
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    if (
        reference.local_sha256
        and local_model_hash(Path(reference.model_id)) != reference.local_sha256
    ):
        raise ValueError("Local base model fingerprint changed")
    kwargs = {"trust_remote_code": False, "use_safetensors": True, "revision": reference.revision}
    if spec.quantization == "nf4":
        if device != "cuda" or not torch.cuda.is_available():
            raise ValueError("This QLoRA path requires supported CUDA hardware")
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float32,
            bnb_4bit_use_double_quant=spec.double_quantization,
        )
        kwargs["device_map"] = {"": 0}
    else:
        kwargs["dtype"] = torch.float32
    model = AutoModelForCausalLM.from_pretrained(reference.model_id, **kwargs)
    if spec.quantization == "none":
        model.to(device)
    return model


class ArtifactManifest(StrictRecord):
    schema_version: Literal[1] = 1
    base: ModelReference
    tokenizer_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    loading: LoadingSpec
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    train_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    validation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    test_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    test_cases_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    max_input_tokens: int = Field(ge=64, le=8192)
    max_new_tokens: int = Field(default=64, ge=16, le=256)
    output_policy: Literal["finite-labels-v1"] | None = None
    derived_from_artifact_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    files: dict[str, str]
    training: dict[str, str | int | float | bool]

    @model_validator(mode="after")
    def tokenizer_matches(self):
        if self.tokenizer_revision != self.base.revision:
            raise ValueError("Tokenizer and base model revisions must match")
        for name, digest in self.files.items():
            if Path(name).name != name or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError("Invalid artifact file entry")
        required = {"adapter_config.json", "adapter_model.safetensors", "tokenizer_config.json"}
        if not required.issubset(self.files):
            raise ValueError("Adapter artifact is incomplete")
        return self

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        # Preserve fingerprints and release bindings of all pre-policy artifacts.
        for name in ("output_policy", "derived_from_artifact_sha256"):
            if payload[name] is None:
                payload.pop(name)
        return canonical_hash(payload)


def verify_artifact(path: Path) -> ArtifactManifest:
    manifest_path = path / ARTIFACT_FILE
    if manifest_path.stat().st_size > 256 * 1024:
        raise ValueError("Artifact manifest too large")
    manifest = ArtifactManifest.model_validate_json(manifest_path.read_bytes())
    expected_prompt = hashlib.sha256(CLASSIFIER_SYSTEM_PROMPT.encode()).hexdigest()
    if manifest.prompt_sha256 != expected_prompt:
        raise ValueError("Training and serving prompt versions differ")
    for name, digest in manifest.files.items():
        file = path / name
        if file.is_symlink() or not file.is_file() or file_sha256(file) != digest:
            raise ValueError("Artifact file missing or modified")
    return manifest


def write_artifact(path: Path, **metadata) -> ArtifactManifest:
    files = {
        file.name: file_sha256(file)
        for file in sorted(path.iterdir())
        if file.is_file()
        and file.name not in {ARTIFACT_FILE, "latest_checkpoint.json"}
        and file.suffix in {".json", ".safetensors", ".model", ".txt", ".jinja"}
    }
    manifest = ArtifactManifest(files=files, **metadata)
    atomic_json(path / ARTIFACT_FILE, manifest.model_dump(mode="json"))
    return manifest


def export_artifact(source: Path, destination: Path) -> ArtifactManifest:
    """Copy only verified inference files, excluding checkpoints and optimizer state."""
    manifest = verify_artifact(source)
    if destination.exists():
        raise ValueError("Artifact destination must not exist")
    destination.mkdir(parents=True)
    try:
        for name in [*manifest.files, ARTIFACT_FILE]:
            shutil.copy2(source / name, destination / name)
        verified = verify_artifact(destination)
        if verified.fingerprint() != manifest.fingerprint():
            raise ValueError("Packaged artifact identity changed")
        return verified
    except BaseException:
        shutil.rmtree(destination)
        raise
