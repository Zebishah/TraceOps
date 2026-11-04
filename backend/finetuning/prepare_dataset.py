"""Validate records, prepare grouped splits and optionally create an unapproved review template."""

import argparse
from pathlib import Path

from finetuning.artifacts import atomic_json
from ops_pilot.finetuning.dataset import dataset_fingerprint, load_examples, write_splits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--review-template", type=Path)
    args = parser.parse_args()
    if args.review_template and args.review_template.exists():
        raise ValueError("Review attestations are never overwritten")
    examples = load_examples(args.input)
    write_splits(examples=examples, output=args.output, seed=args.seed)
    if args.review_template:
        atomic_json(
            args.review_template,
            {
                "dataset_sha256": dataset_fingerprint(examples),
                "source": "unreviewed",
                "reviewer": "",
                "reviewed_at": None,
                "labels_approved": False,
                "deidentified": False,
            },
        )
    print(f"Prepared {len(examples)} labeled examples; see {args.output / 'manifest.json'}")


if __name__ == "__main__":
    main()
