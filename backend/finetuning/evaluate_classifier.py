"""Evaluate strict label accuracy against independent reviewed incidents."""

import argparse
import asyncio
import json
from pathlib import Path

from finetuning.model_runtime import load_runtime, predict_labels
from ops_pilot.finetuning.dataset import load_examples


async def evaluate(args) -> None:
    examples = load_examples(args.input)
    correct_category = correct_priority = correct_both = invalid = 0
    cases = []
    if args.backend == "adapter":
        if args.adapter is None:
            raise ValueError("--adapter is required for adapter evaluation")
        model, tokenizer = load_runtime(args.adapter, device=args.device, qlora=args.qlora)
    for index, example in enumerate(examples):
        try:
            if args.backend == "adapter":
                result = predict_labels(
                    model, tokenizer, title=example.title, description=example.description
                )
            else:
                from ops_pilot.ai.incident_classifier import _classify_with_groq

                result = await _classify_with_groq(
                    title=example.title,
                    description=example.description,
                )
            category_ok = result.category == example.category
            priority_ok = result.priority == example.priority
            correct_category += category_ok
            correct_priority += priority_ok
            correct_both += category_ok and priority_ok
            cases.append(
                {
                    "index": index,
                    "category_correct": category_ok,
                    "priority_correct": priority_ok,
                    "invalid": False,
                }
            )
        except (ValueError, RuntimeError):
            invalid += 1
            cases.append({"index": index, "invalid": True})
    total = len(examples)
    report = {
        "backend": args.backend,
        "total": total,
        "category_accuracy": correct_category / total,
        "priority_accuracy": correct_priority / total,
        "joint_accuracy": correct_both / total,
        "invalid_outputs": invalid,
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=["groq", "adapter"], required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--qlora", action="store_true")
    asyncio.run(evaluate(parser.parse_args()))


if __name__ == "__main__":
    main()
