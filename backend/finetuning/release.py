"""Offline Ed25519 approval of evaluated artifacts; workers hold public keys only."""

import argparse
import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from finetuning.artifacts import atomic_json, file_sha256, verify_artifact
from ops_pilot.finetuning.quality import (
    DatasetReview,
    EvaluationReport,
    PromotionPolicy,
    StrictRecord,
    canonical_hash,
    expected_case_map,
    promotion_failures,
)


class ReleasePayload(StrictRecord):
    schema_version: Literal[1] = 1
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    adapter_report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    baseline_report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_at: datetime
    reviewer: str = Field(min_length=3)
    policy: PromotionPolicy


class SignedRelease(StrictRecord):
    payload: ReleasePayload
    signature: str


def _signing_bytes(payload: ReleasePayload) -> bytes:
    return (
        b"opspilot-classifier-release-v1:"
        + canonical_hash(payload.model_dump(mode="json")).encode()
    )


def _read_json(path: Path) -> bytes:
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Release evidence exceeds size limit")
    return path.read_bytes()


def approve_release(
    *,
    adapter_path: Path,
    adapter_report: Path,
    baseline_report: Path,
    review_path: Path,
    private_key: bytes,
    output: Path,
    policy: PromotionPolicy | None = None,
) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if output.exists():
        raise ValueError("Existing release is never overwritten")
    artifact = verify_artifact(adapter_path)
    candidate = EvaluationReport.model_validate_json(_read_json(adapter_report))
    baseline = EvaluationReport.model_validate_json(_read_json(baseline_report))
    review = DatasetReview.model_validate_json(_read_json(review_path))
    selected_policy = policy or PromotionPolicy()
    failures = promotion_failures(candidate, baseline, review, selected_policy)
    if candidate.artifact_sha256 != artifact.fingerprint():
        failures.append("Evaluation belongs to a different adapter artifact")
    if candidate.dataset_sha256 != artifact.dataset_sha256:
        failures.append("Evaluation dataset differs from training provenance")
    if not artifact.test_sha256 or candidate.input_sha256 != artifact.test_sha256:
        failures.append("Evaluation is not the artifact's held-out test file")
    evaluated_cases = expected_case_map(candidate.cases)
    if (
        not artifact.test_cases_sha256
        or canonical_hash(evaluated_cases) != artifact.test_cases_sha256
    ):
        failures.append("Evaluation cases differ from the held-out test set")
    if (
        candidate.model != artifact.base.model_id
        or candidate.model_revision != artifact.base.revision
    ):
        failures.append("Evaluation model identity differs from adapter artifact")
    if not artifact.base.revision:
        failures.append("Production releases require a pinned Hub model revision")
    if review.reviewed_at > datetime.now(UTC):
        failures.append("Review timestamp is in the future")
    if failures:
        raise ValueError("Promotion rejected: " + "; ".join(failures))
    payload = ReleasePayload(
        artifact_sha256=artifact.fingerprint(),
        dataset_sha256=artifact.dataset_sha256,
        adapter_report_sha256=file_sha256(adapter_report),
        baseline_report_sha256=file_sha256(baseline_report),
        review_sha256=file_sha256(review_path),
        approved_at=datetime.now(UTC),
        reviewer=review.reviewer,
        policy=selected_policy,
    )
    signature = Ed25519PrivateKey.from_private_bytes(private_key).sign(_signing_bytes(payload))
    release = SignedRelease(payload=payload, signature=base64.b64encode(signature).decode())
    atomic_json(output, release.model_dump(mode="json"))
    return canonical_hash(payload.model_dump(mode="json"))


def verify_release(adapter_path: Path, release_path: Path, public_key: bytes) -> str:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if release_path.stat().st_size > 64 * 1024:
        raise ValueError("Release manifest exceeds size limit")
    release = SignedRelease.model_validate_json(release_path.read_bytes())
    try:
        signature = base64.b64decode(release.signature, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, _signing_bytes(release.payload)
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("Release signature invalid") from exc
    artifact = verify_artifact(adapter_path)
    if release.payload.artifact_sha256 != artifact.fingerprint():
        raise ValueError("Release does not authorize this adapter")
    if release.payload.dataset_sha256 != artifact.dataset_sha256:
        raise ValueError("Release dataset mismatch")
    if not artifact.base.revision or release.payload.approved_at.tzinfo is None:
        raise ValueError("Production model identity and release timestamp must be pinned")
    if release.payload.approved_at > datetime.now(UTC):
        raise ValueError("Release timestamp is in the future")
    return canonical_hash(release.payload.model_dump(mode="json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    keys = commands.add_parser("generate-key")
    keys.add_argument("--private-file", type=Path, required=True)
    keys.add_argument("--public-file", type=Path, required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("--adapter", type=Path, required=True)
    approve.add_argument("--adapter-report", type=Path, required=True)
    approve.add_argument("--baseline-report", type=Path, required=True)
    approve.add_argument("--review", type=Path, required=True)
    approve.add_argument("--private-key-file", type=Path, required=True)
    approve.add_argument("--output", type=Path, required=True)
    approve.add_argument("--policy", type=Path)
    args = parser.parse_args()
    if args.command == "generate-key":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        if args.private_file.exists() or args.public_file.exists():
            raise ValueError("Signing keys are never overwritten")
        key = Ed25519PrivateKey.generate()
        args.private_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(args.private_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(key.private_bytes_raw())
        args.public_file.parent.mkdir(parents=True, exist_ok=True)
        args.public_file.write_text(
            base64.b64encode(key.public_key().public_bytes_raw()).decode() + "\n"
        )
        print("Created signing key and public verification key; keep the private key offline.")
    else:
        policy = (
            PromotionPolicy.model_validate_json(args.policy.read_bytes()) if args.policy else None
        )
        release_id = approve_release(
            adapter_path=args.adapter,
            adapter_report=args.adapter_report,
            baseline_report=args.baseline_report,
            review_path=args.review,
            private_key=args.private_key_file.read_bytes(),
            output=args.output,
            policy=policy,
        )
        print(json.dumps({"release_id": release_id}))


if __name__ == "__main__":
    main()
