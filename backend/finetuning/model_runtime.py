"""Optional ML imports and one shared training/inference prompt contract."""

import json
import os
from pathlib import Path

from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.finetuning.dataset import classifier_messages


def load_runtime(adapter_path: Path, *, device: str = "cpu", qlora: bool = False):
    # Import lazily: ordinary backend installations never need these packages.
    import torch
    from peft import PeftConfig, PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    config = PeftConfig.from_pretrained(str(adapter_path))
    kwargs = {"trust_remote_code": False, "use_safetensors": True}
    if qlora:
        if not torch.cuda.is_available() or device != "cuda":
            raise ValueError("QLoRA requires a supported CUDA GPU and bitsandbytes")
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True)
        kwargs["device_map"] = {"": 0}
    else:
        kwargs["dtype"] = torch.float32
    base = AutoModelForCausalLM.from_pretrained(config.base_model_name_or_path, **kwargs)
    model = PeftModel.from_pretrained(base, str(adapter_path), is_trainable=False)
    if not qlora:
        model.to(device)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(str(adapter_path), trust_remote_code=False)
    return model, tokenizer


def predict_labels(model, tokenizer, *, title: str, description: str) -> ClassifierLabels:
    import torch

    messages = classifier_messages(title=title, description=description)
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
    max_input = int(os.getenv("CLASSIFIER_MAX_INPUT_TOKENS", "1024"))
    if max_input < 64 or max_input > 8192:
        raise ValueError("CLASSIFIER_MAX_INPUT_TOKENS must be between 64 and 8192")
    if inputs.input_ids.shape[1] > max_input:
        raise ValueError("Incident exceeds classifier input token budget")
    inputs = inputs.to(model.device)
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=64,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = tokenizer.decode(output[0, inputs.input_ids.shape[1] :], skip_special_tokens=True)
    # Strict JSON only; malformed labels cause API fallback, never invented labels.
    return ClassifierLabels.model_validate(json.loads(generated))
