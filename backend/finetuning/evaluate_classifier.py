"""Held-out, paired classification reports with safety, latency and memory metrics."""

import argparse
import asyncio
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from finetuning.artifacts import atomic_json, file_sha256, verify_artifact
from finetuning.process_worker import InvalidPrediction, ProcessModelWorker
from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.finetuning.dataset import verified_splits
from ops_pilot.finetuning.quality import EvaluationCase, EvaluationReport, canonical_hash


def peak_rss_mib():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024 if sys.platform == "darwin" else 1024)


async def evaluate(args) -> EvaluationReport:
    if args.output.exists() or args.output.with_suffix(".summary.json").exists():
        raise ValueError("Evaluation reports are never overwritten")
    split = getattr(args, "split", None) or args.input.stem
    if split not in {"validation", "test"} or args.input.name != f"{split}.jsonl":
        raise ValueError("Use an exact prepared validation.jsonl or test.jsonl split")
    splits, dataset_hash = verified_splits(args.input.parent)
    examples = splits[split]
    artifact = None
    worker = None
    model_name = ""
    revision = None
    if args.backend in {"adapter", "base"}:
        if args.adapter is None:
            raise ValueError("Adapter artifact is required to pin model/loading identity")
        artifact = verify_artifact(args.adapter)
        if artifact.dataset_sha256 != dataset_hash:
            raise ValueError("Evaluation dataset differs from the trained artifact")
        model_name, revision = artifact.base.model_id, artifact.base.revision
        worker = ProcessModelWorker(
            args.adapter,
            device=args.device,
            qlora=args.qlora,
            prediction_timeout=getattr(args, "timeout_seconds", 8),
            startup_timeout=getattr(args, "startup_timeout_seconds", 120),
            base_only=args.backend == "base",
        )
        await worker.start()
    else:
        from ops_pilot.core.config import get_settings

        model_name = get_settings().generation_model
    cases = []
    try:
        for example in examples:
            started = time.perf_counter()
            prediction = None
            error = None
            try:
                if worker is not None:
                    prediction = await worker.predict(
                        title=example.title, description=example.description
                    )
                else:
                    from ops_pilot.ai.incident_classifier import _classify_with_groq

                    async with asyncio.timeout(getattr(args, "timeout_seconds", 8)):
                        result = await _classify_with_groq(
                            title=example.title, description=example.description
                        )
                    prediction = ClassifierLabels(
                        category=result.category, priority=result.priority
                    )
            except (InvalidPrediction, ValueError):
                error = "invalid_output"
            except Exception:
                error = "infrastructure"
            cases.append(
                EvaluationCase(
                    case_id=canonical_hash(
                        {"title": example.title, "description": example.description}
                    ),
                    group_id=canonical_hash({"group_id": example.group_id}),
                    expected=ClassifierLabels(category=example.category, priority=example.priority),
                    predicted=prediction,
                    error=error,
                    latency_seconds=time.perf_counter() - started,
                )
            )
    finally:
        if worker is not None:
            await worker.close()
    report = EvaluationReport(
        backend=args.backend,
        split=split,
        dataset_sha256=dataset_hash,
        input_sha256=file_sha256(args.input),
        artifact_sha256=artifact.fingerprint() if artifact and args.backend == "adapter" else None,
        model=model_name,
        model_revision=revision,
        created_at=datetime.now(UTC),
        peak_rss_mib=peak_rss_mib() + (worker.peak_rss_mib if worker else 0),
        cases=cases,
    )
    atomic_json(args.output, report.model_dump(mode="json"))
    summary = {
        "backend": args.backend,
        "split": split,
        "model": model_name,
        "artifact_sha256": report.artifact_sha256,
        "peak_rss_mib": report.peak_rss_mib,
        **report.metrics(),
    }
    atomic_json(args.output.with_suffix(".summary.json"), summary)
    import json

    print(json.dumps(summary, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=["validation", "test"])
    parser.add_argument("--backend", choices=["groq", "adapter", "base"], required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--qlora", action="store_true", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=8)
    parser.add_argument("--startup-timeout-seconds", type=float, default=120)
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= 60 or not 0 < args.startup_timeout_seconds <= 600:
        raise ValueError("Invalid evaluation deadline")
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
