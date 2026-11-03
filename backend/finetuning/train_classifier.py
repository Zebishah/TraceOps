"""Supervised LoRA/QLoRA training with response-only loss and held-out validation.

This is an offline command, never an HTTP endpoint or background production job.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import random
from pathlib import Path

from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.finetuning.dataset import classifier_messages, load_examples


def encode_example(tokenizer, example, *, max_tokens: int):
    messages = classifier_messages(title=example.title, description=example.description)
    prompt_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    labels = ClassifierLabels(category=example.category, priority=example.priority)
    complete_text = tokenizer.apply_chat_template(
        [*messages, {"role": "assistant", "content": labels.model_dump_json()}],
        tokenize=False,
        add_generation_prompt=False,
    )
    if not complete_text.startswith(prompt_text) or len(complete_text) <= len(prompt_text):
        raise ValueError("Model chat template does not support response-only supervision")
    # Tokenize at the same boundary used at inference. Some tokenizers merge
    # the last prompt character with the answer if the whole string is encoded.
    prompt = tokenizer.encode(prompt_text, add_special_tokens=False)
    completion = tokenizer.encode(complete_text[len(prompt_text) :], add_special_tokens=False)
    complete = prompt + completion
    if len(complete) > max_tokens:
        raise ValueError(
            "Training example exceeds token limit; shorten it instead of truncating labels"
        )
    return {"input_ids": complete, "labels": [-100] * len(prompt) + complete[len(prompt) :]}


def train(args) -> None:
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Adapter output must be empty; existing adapters are never overwritten")
    if (
        args.epochs < 1
        or args.gradient_accumulation < 1
        or not math.isfinite(args.learning_rate)
        or args.learning_rate <= 0
    ):
        raise ValueError("Epochs, accumulation and learning rate must be positive")
    if not 128 <= args.max_tokens <= 8192 or args.max_steps < 0:
        raise ValueError("Invalid token budget or step limit")
    train_examples = load_examples(args.data / "train.jsonl")
    validation_examples = load_examples(args.data / "validation.jsonl")
    if {e.group_id for e in train_examples} & {e.group_id for e in validation_examples}:
        raise ValueError("Training and validation groups overlap")
    torch.manual_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=False)
    kwargs = {"trust_remote_code": False, "use_safetensors": True}
    if args.qlora:
        if args.device != "cuda" or not torch.cuda.is_available():
            raise ValueError("QLoRA needs supported CUDA hardware and bitsandbytes")
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float32,
        )
        kwargs["device_map"] = {"": 0}
    else:
        kwargs["dtype"] = torch.float32
    model = AutoModelForCausalLM.from_pretrained(args.model, **kwargs)
    if args.qlora:
        model = prepare_model_for_kbit_training(model)
    model = get_peft_model(
        model,
        LoraConfig(
            task_type="CAUSAL_LM",
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            target_modules="all-linear",
            bias="none",
        ),
    )
    if not args.qlora:
        model.to(args.device)
    model.config.use_cache = False
    records = [encode_example(tokenizer, e, max_tokens=args.max_tokens) for e in train_examples]
    validation = [
        encode_example(tokenizer, e, max_tokens=args.max_tokens) for e in validation_examples
    ]
    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad),
        lr=args.learning_rate,
    )
    history = []
    steps = 0
    for epoch in range(args.epochs):
        model.train()
        order = list(range(len(records)))
        random.Random(args.seed + epoch).shuffle(order)
        for start in range(0, len(order), args.gradient_accumulation):
            group = order[start : start + args.gradient_accumulation]
            optimizer.zero_grad(set_to_none=True)
            for index in group:
                inputs = {
                    key: torch.tensor([value], device=model.device)
                    for key, value in records[index].items()
                }
                loss = model(**inputs).loss
                if not torch.isfinite(loss):
                    raise RuntimeError("Nonfinite training loss; adapter was not saved")
                (loss / len(group)).backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            steps += 1
            if args.max_steps and steps >= args.max_steps:
                break
        model.eval()
        losses = []
        with torch.inference_mode():
            for record in validation:
                inputs = {
                    key: torch.tensor([value], device=model.device) for key, value in record.items()
                }
                losses.append(float(model(**inputs).loss))
        history.append({"epoch": epoch + 1, "validation_loss": sum(losses) / len(losses)})
        print(json.dumps(history[-1]))
        if args.max_steps and steps >= args.max_steps:
            break
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(args.output), safe_serialization=True)
    tokenizer.save_pretrained(str(args.output))
    manifest = {
        "base_model": args.model,
        "method": "qlora" if args.qlora else "lora",
        "seed": args.seed,
        "optimizer_steps": steps,
        "validation": history,
        "train_sha256": hashlib.sha256((args.data / "train.jsonl").read_bytes()).hexdigest(),
        "versions": {
            name: importlib.metadata.version(name) for name in ("torch", "transformers", "peft")
        },
        "note": "Evaluate on untouched test data before enabling the adapter.",
    }
    (args.output / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--qlora", action="store_true")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument(
        "--max-steps", type=int, default=0, help="0 = full run; small values = smoke test"
    )
    parser.add_argument("--gradient-accumulation", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--seed", type=int, default=42)
    train(parser.parse_args())


if __name__ == "__main__":
    main()
