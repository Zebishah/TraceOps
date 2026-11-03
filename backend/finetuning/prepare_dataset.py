"""Validate explicitly supplied, reviewed records and prepare leakage-safe splits."""

import argparse
from pathlib import Path

from ops_pilot.finetuning.dataset import load_examples, write_splits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    examples = load_examples(args.input)
    write_splits(examples=examples, output=args.output, seed=args.seed)
    print(f"Prepared {len(examples)} labeled examples; see {args.output / 'manifest.json'}")


if __name__ == "__main__":
    main()
