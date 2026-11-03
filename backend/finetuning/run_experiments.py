"""Reproducible sequential experiments; select on validation, never the test set."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from pydantic import Field

from finetuning.artifacts import atomic_json
from ops_pilot.finetuning.quality import EvaluationReport, StrictRecord


class Experiment(StrictRecord):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,60}$")
    model: str
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    rank: int = Field(default=8, ge=1, le=256)
    alpha: int = Field(default=16, ge=1)
    dropout: float = Field(default=0.05, ge=0, lt=1)
    learning_rate: float = Field(default=0.0002, gt=0)
    epochs: int = Field(default=3, ge=1, le=20)
    max_steps: int = Field(default=0, ge=0)
    max_tokens: int = Field(default=1024, ge=128, le=8192)
    gradient_accumulation: int = Field(default=4, ge=1, le=128)
    seed: int = 42


class ExperimentPlan(StrictRecord):
    experiments: list[Experiment] = Field(min_length=1, max_length=20)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--qlora", action="store_true")
    args = parser.parse_args()
    plan = ExperimentPlan.model_validate_json(args.config.read_bytes())
    if len({run.name for run in plan.experiments}) != len(plan.experiments):
        raise ValueError("Experiment names must be unique")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Experiment output must be empty")
    args.output.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output / "plan.json", plan.model_dump(mode="json"))
    results = []
    for run in plan.experiments:
        adapter = args.output / run.name / "adapter"
        report = args.output / run.name / "validation.json"
        command = [
            sys.executable,
            "-m",
            "finetuning.train_classifier",
            "--data",
            str(args.data),
            "--output",
            str(adapter),
            "--device",
            args.device,
        ]
        for key, value in run.model_dump(exclude={"name"}).items():
            command.extend(["--" + key.replace("_", "-"), str(value)])
        if args.qlora:
            command.append("--qlora")
        subprocess.run(command, check=True)
        command = [
            sys.executable,
            "-m",
            "finetuning.evaluate_classifier",
            "--backend",
            "adapter",
            "--adapter",
            str(adapter),
            "--input",
            str(args.data / "validation.jsonl"),
            "--split",
            "validation",
            "--output",
            str(report),
            "--device",
            args.device,
        ]
        if args.qlora:
            command.append("--qlora")
        subprocess.run(command, check=True)
        measured = EvaluationReport.model_validate_json(report.read_bytes())
        results.append({"name": run.name, "adapter": str(adapter), "metrics": measured.metrics()})
        atomic_json(args.output / "results.json", results)
    valid = [
        run
        for run in results
        if not run["metrics"]["infrastructure_errors"]
        and run["metrics"]["invalid_outputs"] < run["metrics"]["total"]
    ]
    if not valid:
        raise RuntimeError("No experiment produced usable validation predictions")
    selected = max(
        valid,
        key=lambda run: (
            -run["metrics"]["critical_misses"],
            -run["metrics"]["high_risk_downgrades"],
            run["metrics"]["joint_accuracy"],
            run["metrics"]["category"]["macro_f1"],
            -run["metrics"]["latency_p95_seconds"],
        ),
    )
    atomic_json(
        args.output / "selected.json",
        {
            "name": selected["name"],
            "adapter": selected["adapter"],
            "selection_split": "validation",
            "production_approved": False,
            "next_step": (
                "Evaluate this selected adapter once on held-out test data and compare with Groq."
            ),
        },
    )
    print(json.dumps({"selected": selected["name"], "production_approved": False}))


if __name__ == "__main__":
    main()
