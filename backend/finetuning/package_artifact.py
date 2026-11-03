"""Package verified inference files without datasets, checkpoints or optimizer state."""

import argparse
import json
from pathlib import Path

from finetuning.artifacts import export_artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = export_artifact(args.input, args.output)
    print(json.dumps({"artifact_sha256": artifact.fingerprint()}))


if __name__ == "__main__":
    main()
