"""Optional real, offline training smoke test. No model download or provider calls."""

import argparse
import json
from pathlib import Path

import pytest

from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")


def test_train_and_reload_real_lora_adapter(tmp_path):
    from safetensors.torch import load_file
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

    from finetuning.model_runtime import load_runtime
    from finetuning.train_classifier import encode_example, train
    from ops_pilot.finetuning.dataset import IncidentExample, classifier_messages, write_splits

    torch.set_num_threads(1)
    examples = [
        IncidentExample(
            title=f"Duplicate payment {i}",
            description=f"Customer has two charges for order {i}.",
            category="payment",
            priority="high",
            group_id=f"independent-{i}",
        )
        for i in range(10)
    ]
    texts = [
        json.dumps(classifier_messages(title=e.title, description=e.description)) for e in examples
    ]
    raw = Tokenizer(models.BPE(unk_token="[UNK]"))
    raw.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    raw.decoder = decoders.ByteLevel()
    raw.train_from_iterator(
        texts,
        trainers.BpeTrainer(
            vocab_size=400,
            special_tokens=["[UNK]", "[EOS]", "[PAD]"],
            initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        ),
    )
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=raw, unk_token="[UNK]", eos_token="[EOS]", pad_token="[PAD]"
    )
    tokenizer.chat_template = (
        "{% for message in messages %}{{ message['role'] + ': ' + message['content'] + '\\n' }}"
        "{% if message['role'] == 'assistant' %}{{ eos_token }}{% endif %}{% endfor %}"
        "{% if add_generation_prompt %}{{ 'assistant: ' }}{% endif %}"
    )
    base = tmp_path / "tiny-base"
    tokenizer.save_pretrained(str(base))
    model = GPT2LMHeadModel(
        GPT2Config(
            vocab_size=len(tokenizer),
            n_positions=2048,
            n_ctx=2048,
            n_embd=16,
            n_layer=1,
            n_head=2,
            bos_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
        )
    )
    model.save_pretrained(str(base), safe_serialization=True)
    record = encode_example(tokenizer, examples[0], max_tokens=2048)
    assert -100 in record["labels"]
    assert any(label >= 0 for label in record["labels"])
    data = tmp_path / "data"
    write_splits(examples=examples, output=data)
    output = tmp_path / "adapter"
    args = argparse.Namespace(
        data=data,
        output=output,
        model=str(base),
        device="cpu",
        qlora=False,
        epochs=1,
        max_tokens=2048,
        max_steps=1,
        gradient_accumulation=1,
        learning_rate=2e-4,
        seed=42,
    )
    train(args)
    assert (output / "adapter_model.safetensors").exists()
    weights = load_file(str(output / "adapter_model.safetensors"))
    assert any(t.abs().sum().item() > 0 for k, t in weights.items() if "lora_B" in k)
    manifest = json.loads((output / "training_manifest.json").read_text())
    assert manifest["optimizer_steps"] == 1
    assert manifest["validation"][0]["validation_loss"] > 0
    restored, restored_tokenizer = load_runtime(output)
    assert not any(p.requires_grad for p in restored.parameters())

    from finetuning.model_runtime import predict_labels

    assert restored.opspilot_manifest.output_policy == "finite-labels-v1"
    # Exercise actual Transformers generation with a real adapter and the token constraint.
    generated = predict_labels(
        restored,
        restored_tokenizer,
        title="Service reports storage pressure",
        description="A full disk is blocking the important dispatch workflow.",
    )
    assert generated.category in set(IncidentCategory)
    assert generated.priority in set(IncidentPriority)

    from finetuning.artifacts import verify_artifact

    artifact = verify_artifact(output)
    assert artifact.base.local_sha256
    assert artifact.test_sha256 and artifact.test_cases_sha256
    from finetuning.artifacts import ARTIFACT_FILE, atomic_json, export_artifact
    from finetuning.constrain_classifier import constrain_artifact

    legacy_path = tmp_path / "legacy-package"
    export_artifact(output, legacy_path)
    legacy_manifest = artifact.model_dump(mode="json")
    legacy_manifest.pop("output_policy")
    legacy_manifest.pop("derived_from_artifact_sha256")
    atomic_json(legacy_path / ARTIFACT_FILE, legacy_manifest)
    parent, derived = constrain_artifact(legacy_path, tmp_path / "converted-package")
    assert parent == verify_artifact(legacy_path).fingerprint()
    assert derived != parent
    converted_model, converted_tokenizer = load_runtime(tmp_path / "converted-package")
    converted_prediction = predict_labels(
        converted_model,
        converted_tokenizer,
        title="Storage warning",
        description="A test disk warning has no actual service impact.",
    )
    assert converted_prediction.category in set(IncidentCategory)
    checkpoint = Path(json.loads((output / "latest_checkpoint.json").read_text())["path"])
    state = json.loads((checkpoint / "checkpoint.json").read_text())
    assert state["epoch"] == 0 and state["next_start"] == 1
    args.resume_from = checkpoint
    args.max_steps = 2
    train(args)
    resumed_checkpoint = Path(json.loads((output / "latest_checkpoint.json").read_text())["path"])
    resumed_weights = load_file(str(resumed_checkpoint / "adapter_model.safetensors"))

    uninterrupted = argparse.Namespace(**vars(args))
    uninterrupted.output = tmp_path / "uninterrupted"
    uninterrupted.resume_from = None
    train(uninterrupted)
    full_checkpoint = Path(
        json.loads((uninterrupted.output / "latest_checkpoint.json").read_text())["path"]
    )
    full_weights = load_file(str(full_checkpoint / "adapter_model.safetensors"))
    assert resumed_weights.keys() == full_weights.keys()
    assert all(
        torch.allclose(resumed_weights[key], full_weights[key], atol=1e-6) for key in full_weights
    )
    best = json.loads((output / "training_manifest.json").read_text())
    assert best["best_validation_loss"] == min(row["validation_loss"] for row in best["validation"])
    args.learning_rate = 0.1
    with pytest.raises(ValueError, match="Resume settings"):
        train(args)
