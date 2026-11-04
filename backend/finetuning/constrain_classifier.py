"""Create a separately identified finite-label package without changing trained weights."""

import argparse
import shutil
from pathlib import Path

from finetuning.artifacts import ARTIFACT_FILE, atomic_json, export_artifact, verify_artifact
from finetuning.label_decoding import FINITE_LABEL_POLICY, FiniteLabelDecoder


def validate_tokenizer(path: Path, max_new_tokens: int) -> None:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(path), trust_remote_code=False, local_files_only=True
    )
    FiniteLabelDecoder(tokenizer, max_new_tokens=max_new_tokens)


def constrain_artifact(source: Path, destination: Path) -> tuple[str, str]:
    original = verify_artifact(source)
    if original.output_policy == FINITE_LABEL_POLICY:
        raise ValueError("Source already uses finite label decoding")
    if destination.exists():
        raise ValueError("Destination must not exist; original artifacts are never overwritten")
    validate_tokenizer(source, original.max_new_tokens)
    export_artifact(source, destination)
    try:
        updated = original.model_copy(
            update={
                "output_policy": FINITE_LABEL_POLICY,
                "derived_from_artifact_sha256": original.fingerprint(),
            }
        )
        atomic_json(destination / ARTIFACT_FILE, updated.model_dump(mode="json"))
        verified = verify_artifact(destination)
        return original.fingerprint(), verified.fingerprint()
    except BaseException:
        shutil.rmtree(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original, constrained = constrain_artifact(args.source, args.output)
    print(f"Original artifact: {original}")
    print(f"Constrained artifact: {constrained}")
    print(f"Saved finite-label package to {args.output}; weights unchanged, evaluation required.")


if __name__ == "__main__":
    main()
