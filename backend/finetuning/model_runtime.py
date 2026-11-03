"""Verified adapter loading and shared, bounded classification inference."""

import json
import os
from pathlib import Path

from finetuning.artifacts import load_base, verify_artifact
from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.finetuning.dataset import classifier_messages


def load_runtime(
    adapter_path: Path,
    *,
    device: str = "cpu",
    qlora: bool | None = None,
    with_adapter: bool = True,
):
    from peft import PeftConfig, PeftModel
    from transformers import AutoTokenizer

    manifest = verify_artifact(adapter_path)
    if qlora is not None and qlora != (manifest.loading.quantization == "nf4"):
        raise ValueError("Requested quantization differs from the trained artifact")
    config = PeftConfig.from_pretrained(str(adapter_path))
    if config.base_model_name_or_path != manifest.base.model_id:
        raise ValueError("Adapter and artifact refer to different base models")
    base = load_base(manifest.base, manifest.loading, device=device)
    model = (
        PeftModel.from_pretrained(base, str(adapter_path), is_trainable=False)
        if with_adapter
        else base
    )
    model.config.use_cache = True
    model.eval()
    model.opspilot_manifest = manifest
    tokenizer = AutoTokenizer.from_pretrained(str(adapter_path), trust_remote_code=False)
    return model, tokenizer


def predict_labels(model, tokenizer, *, title: str, description: str) -> ClassifierLabels:
    import torch

    manifest = model.opspilot_manifest
    messages = classifier_messages(title=title, description=description)
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
    max_input = int(os.getenv("CLASSIFIER_MAX_INPUT_TOKENS", str(manifest.max_input_tokens)))
    if not 64 <= max_input <= manifest.max_input_tokens:
        raise ValueError("Input token budget may only tighten the verified artifact limit")
    if inputs.input_ids.shape[1] > max_input:
        raise ValueError("Incident exceeds classifier input token budget")
    context = getattr(model.config, "max_position_embeddings", max_input + manifest.max_new_tokens)
    if inputs.input_ids.shape[1] + manifest.max_new_tokens > context:
        raise ValueError("Prediction exceeds model context")
    inputs = inputs.to(model.device)
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=manifest.max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = tokenizer.decode(output[0, inputs.input_ids.shape[1] :], skip_special_tokens=True)
    if len(generated.encode()) > 4096:
        raise ValueError("Generated classification exceeds output limit")
    return ClassifierLabels.model_validate(json.loads(generated))
