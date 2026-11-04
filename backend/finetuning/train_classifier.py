"""Offline response-only LoRA/QLoRA with pinned artifacts and resumable checkpoints."""

import argparse
import hashlib
import importlib.metadata
import json
import math
import random
import re
import shutil
from pathlib import Path

from finetuning.artifacts import (
    LoadingSpec,
    ModelReference,
    atomic_json,
    file_sha256,
    load_base,
    resolve_reference,
    write_artifact,
)
from finetuning.label_decoding import FINITE_LABEL_POLICY
from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.finetuning.dataset import (
    CLASSIFIER_SYSTEM_PROMPT,
    classifier_messages,
    verified_splits,
)
from ops_pilot.finetuning.quality import canonical_hash


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
    prompt = tokenizer.encode(prompt_text, add_special_tokens=False)
    completion = tokenizer.encode(complete_text[len(prompt_text) :], add_special_tokens=False)
    if not completion:
        raise ValueError("Training answer contains no tokens")
    complete = prompt + completion
    if len(complete) > max_tokens:
        raise ValueError("Training example exceeds token limit; shorten it rather than truncate")
    return {"input_ids": complete, "labels": [-100] * len(prompt) + completion}


def _training_settings(args):
    return {
        "rank": getattr(args, "rank", 8),
        "alpha": getattr(args, "alpha", 16),
        "dropout": getattr(args, "dropout", 0.05),
        "learning_rate": args.learning_rate,
        "gradient_accumulation": args.gradient_accumulation,
        "max_tokens": args.max_tokens,
        "seed": args.seed,
    }


def _checkpoint(model, tokenizer, optimizer, directory, state):
    import torch

    name = f"step-{state['steps']:08d}-epoch-{state['epoch']:04d}-next-{state['next_start']:08d}"
    if state.get("validated"):
        name += "-validated"
    destination = directory / name
    if destination.exists():
        return destination
    temporary = directory / (name + ".partial")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    model.save_pretrained(str(temporary), safe_serialization=True)
    tokenizer.save_pretrained(str(temporary))
    rng = {"cpu": torch.get_rng_state()}
    if torch.cuda.is_available():
        rng["cuda"] = torch.cuda.get_rng_state_all()
    torch.save({"optimizer": optimizer.state_dict(), "rng": rng}, temporary / "optimizer.pt")
    state = {
        **state,
        "files": {file.name: file_sha256(file) for file in temporary.iterdir() if file.is_file()},
    }
    atomic_json(temporary / "checkpoint.json", state)
    temporary.replace(destination)
    return destination


def _read_checkpoint(path):
    if (path / "checkpoint.json").stat().st_size > 256 * 1024:
        raise ValueError("Checkpoint manifest exceeds size limit")
    state = json.loads((path / "checkpoint.json").read_text())
    for field in ("steps", "epoch", "next_start", "stale_epochs"):
        if type(state.get(field)) is not int or state[field] < 0:
            raise ValueError("Invalid checkpoint progress")
    best = state.get("best_checkpoint")
    if best is not None and not re.fullmatch(
        r"step-[0-9]{8}-epoch-[0-9]{4}-next-[0-9]{8}(?:-validated)?", best
    ):
        raise ValueError("Invalid best-checkpoint reference")
    for name, digest in state["files"].items():
        file = path / name
        if (
            Path(name).name != name
            or file.is_symlink()
            or not file.is_file()
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or file_sha256(file) != digest
        ):
            raise ValueError("Checkpoint file missing or modified")
    return state


def train(args) -> None:
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoTokenizer

    settings = _training_settings(args)
    if args.epochs < 1 or args.gradient_accumulation < 1:
        raise ValueError("Epochs and gradient accumulation must be positive")
    if not math.isfinite(args.learning_rate) or args.learning_rate <= 0:
        raise ValueError("Learning rate must be positive and finite")
    if not 128 <= args.max_tokens <= 8192 or args.max_steps < 0:
        raise ValueError("Invalid token budget or step limit")
    if not 1 <= settings["rank"] <= 256 or settings["alpha"] <= 0:
        raise ValueError("Invalid LoRA rank or scaling")
    if not math.isfinite(settings["dropout"]) or not 0 <= settings["dropout"] < 1:
        raise ValueError("Invalid dropout")
    patience = getattr(args, "patience", 2)
    save_every = getattr(args, "save_every_steps", 50)
    cpu_threads = getattr(args, "cpu_threads", 2)
    if patience < 0 or save_every < 1 or not 1 <= cpu_threads <= 64:
        raise ValueError("Invalid checkpoint, early-stopping or CPU settings")
    torch.set_num_threads(cpu_threads)
    resume_path = getattr(args, "resume_from", None)
    resumed = _read_checkpoint(resume_path) if resume_path else None
    if args.output.exists() and any(args.output.iterdir()) and not resumed:
        raise ValueError("Adapter output must be empty; existing adapters are never overwritten")
    splits, dataset_hash = verified_splits(args.data)
    train_hash = file_sha256(args.data / "train.jsonl")
    validation_hash = file_sha256(args.data / "validation.jsonl")
    if resumed:
        if (
            resumed["dataset_sha256"] != dataset_hash
            or resumed["train_sha256"] != train_hash
            or resumed["validation_sha256"] != validation_hash
            or resumed["settings"] != settings
        ):
            raise ValueError("Resume settings or dataset differ from the checkpoint")
        reference = ModelReference.model_validate(resumed["base"])
        if args.model != reference.model_id:
            raise ValueError("Resume base model differs from checkpoint")
    else:
        reference = resolve_reference(args.model, getattr(args, "revision", None))
    loading = LoadingSpec(quantization="nf4" if args.qlora else "none")
    if resumed and resumed["loading"] != loading.model_dump():
        raise ValueError("Resume quantization differs from checkpoint")
    torch.manual_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(
        reference.model_id, revision=reference.revision, trust_remote_code=False
    )
    model = load_base(reference, loading, device=args.device)
    context_limit = getattr(model.config, "max_position_embeddings", args.max_tokens)
    if args.max_tokens > context_limit:
        raise ValueError("Token budget exceeds the base model context")
    if args.qlora:
        model = prepare_model_for_kbit_training(model)
    if resumed:
        model = PeftModel.from_pretrained(model, str(resume_path), is_trainable=True)
    else:
        model = get_peft_model(
            model,
            LoraConfig(
                task_type="CAUSAL_LM",
                r=settings["rank"],
                lora_alpha=settings["alpha"],
                lora_dropout=settings["dropout"],
                target_modules="all-linear",
                bias="none",
                revision=reference.revision,
            ),
        )
    model.config.use_cache = False
    records = [encode_example(tokenizer, e, max_tokens=args.max_tokens) for e in splits["train"]]
    validation = [
        encode_example(tokenizer, e, max_tokens=args.max_tokens) for e in splits["validation"]
    ]
    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad), lr=args.learning_rate
    )
    history = resumed["history"] if resumed else []
    steps = resumed["steps"] if resumed else 0
    best_loss = resumed["best_loss"] if resumed else None
    best_checkpoint = resumed["best_checkpoint"] if resumed else None
    stale_epochs = resumed["stale_epochs"] if resumed else 0
    start_epoch = resumed["epoch"] if resumed else 0
    next_start = resumed["next_start"] if resumed else 0
    if resumed:
        state = torch.load(
            resume_path / "optimizer.pt", map_location=model.device, weights_only=True
        )
        optimizer.load_state_dict(state["optimizer"])
        torch.set_rng_state(state["rng"]["cpu"].cpu())
        if "cuda" in state["rng"] and torch.cuda.is_available():
            torch.cuda.set_rng_state_all([value.cpu() for value in state["rng"]["cuda"]])
        if best_checkpoint and not (args.output / "checkpoints" / best_checkpoint).is_dir():
            raise ValueError("Best checkpoint missing; resume into the original output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint_root = args.output / "checkpoints"

    def state_for(epoch, next_position, validated=False):
        return {
            "base": reference.model_dump(),
            "loading": loading.model_dump(),
            "dataset_sha256": dataset_hash,
            "train_sha256": train_hash,
            "validation_sha256": validation_hash,
            "settings": settings,
            "steps": steps,
            "epoch": epoch,
            "next_start": next_position,
            "validated": validated,
            "history": history,
            "best_loss": best_loss,
            "best_checkpoint": best_checkpoint,
            "stale_epochs": stale_epochs,
        }

    for epoch in range(start_epoch, args.epochs):
        model.train()
        order = list(range(len(records)))
        random.Random(args.seed + epoch).shuffle(order)
        progress_position = next_start if epoch == start_epoch else 0
        for start in range(
            next_start if epoch == start_epoch else 0, len(order), args.gradient_accumulation
        ):
            if args.max_steps and steps >= args.max_steps:
                break
            group = order[start : start + args.gradient_accumulation]
            optimizer.zero_grad(set_to_none=True)
            for index in group:
                inputs = {
                    key: torch.tensor([value], device=model.device)
                    for key, value in records[index].items()
                }
                loss = model(**inputs).loss
                if not torch.isfinite(loss):
                    raise RuntimeError("Nonfinite training loss; refusing to publish an adapter")
                (loss / len(group)).backward()
            torch.nn.utils.clip_grad_norm_(
                model.parameters(), max_norm=1.0, error_if_nonfinite=True
            )
            optimizer.step()
            steps += 1
            progress_position = start + len(group)
            if steps % save_every == 0:
                _checkpoint(
                    model,
                    tokenizer,
                    optimizer,
                    checkpoint_root,
                    state_for(epoch, start + len(group)),
                )
        model.eval()
        losses = []
        with torch.inference_mode():
            for record in validation:
                inputs = {
                    key: torch.tensor([value], device=model.device) for key, value in record.items()
                }
                loss = float(model(**inputs).loss)
                if not math.isfinite(loss):
                    raise RuntimeError("Nonfinite validation loss; refusing to publish an adapter")
                losses.append(loss)
        validation_loss = sum(losses) / len(losses)
        completed_epoch = progress_position >= len(order)
        resume_epoch = epoch + 1 if completed_epoch else epoch
        resume_position = 0 if completed_epoch else progress_position
        history.append(
            {
                "epoch": epoch + 1,
                "complete_epoch": completed_epoch,
                "validation_loss": validation_loss,
            }
        )
        improved = best_loss is None or validation_loss < best_loss
        if improved:
            best_loss = validation_loss
            stale_epochs = 0
            best_checkpoint = (
                f"step-{steps:08d}-epoch-{resume_epoch:04d}-next-{resume_position:08d}-validated"
            )
        else:
            stale_epochs += 1
        checkpoint = _checkpoint(
            model,
            tokenizer,
            optimizer,
            checkpoint_root,
            state_for(resume_epoch, resume_position, validated=True),
        )
        atomic_json(args.output / "latest_checkpoint.json", {"path": str(checkpoint.resolve())})
        print(json.dumps(history[-1]))
        if (args.max_steps and steps >= args.max_steps) or (patience and stale_epochs >= patience):
            break
    if not best_checkpoint:
        raise ValueError("No completed validation checkpoint is available")
    selected = checkpoint_root / best_checkpoint
    _read_checkpoint(selected)
    for file in selected.iterdir():
        if (
            file.suffix in {".safetensors", ".json", ".txt", ".model", ".jinja"}
            and file.name != "checkpoint.json"
        ):
            shutil.copy2(file, args.output / file.name)
    versions = {
        name: importlib.metadata.version(name)
        for name in ("torch", "transformers", "peft", "accelerate", "tokenizers", "safetensors")
    }
    manifest = {
        "base_model": reference.model_id,
        "base_revision": reference.revision,
        "method": "qlora" if args.qlora else "lora",
        "output_policy": FINITE_LABEL_POLICY,
        "seed": args.seed,
        "optimizer_steps": steps,
        "validation": history,
        "best_checkpoint": best_checkpoint,
        "best_validation_loss": best_loss,
        "train_sha256": train_hash,
        "validation_sha256": validation_hash,
        "versions": versions,
        "settings": settings,
        "note": (
            "Evaluate on untouched test data; training does not authorize production activation."
        ),
    }
    atomic_json(args.output / "training_manifest.json", manifest)
    write_artifact(
        args.output,
        base=reference,
        tokenizer_revision=reference.revision,
        loading=loading,
        prompt_sha256=hashlib.sha256(CLASSIFIER_SYSTEM_PROMPT.encode()).hexdigest(),
        dataset_sha256=dataset_hash,
        train_sha256=train_hash,
        validation_sha256=validation_hash,
        test_sha256=file_sha256(args.data / "test.jsonl"),
        test_cases_sha256=canonical_hash(
            {
                canonical_hash({"title": e.title, "description": e.description}): {
                    "expected": ClassifierLabels(
                        category=e.category, priority=e.priority
                    ).model_dump(mode="json"),
                    "group_id": canonical_hash({"group_id": e.group_id}),
                }
                for e in splits["test"]
            }
        ),
        max_input_tokens=args.max_tokens - 64,
        output_policy=FINITE_LABEL_POLICY,
        training={**settings, "optimizer_steps": steps, "best_validation_loss": best_loss},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--revision", help="Full Hub commit SHA; resolved and pinned when omitted")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--qlora", action="store_true")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--max-steps", type=int, default=0)
    parser.add_argument("--gradient-accumulation", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--save-every-steps", type=int, default=50)
    parser.add_argument("--patience", type=int, default=2, help="0 disables early stopping")
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--resume-from", type=Path)
    train(parser.parse_args())


if __name__ == "__main__":
    main()
