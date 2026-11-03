"""Optional real, offline training smoke test. No model download or provider calls."""

import argparse
import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")


def test_train_and_reload_real_lora_adapter(tmp_path):
    from safetensors.torch import load_file
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers
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
    train(
        argparse.Namespace(
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
    )
    assert (output / "adapter_model.safetensors").exists()
    weights = load_file(str(output / "adapter_model.safetensors"))
    assert any(t.abs().sum().item() > 0 for k, t in weights.items() if "lora_B" in k)
    manifest = json.loads((output / "training_manifest.json").read_text())
    assert manifest["optimizer_steps"] == 1
    assert manifest["validation"][0]["validation_loss"] > 0
    restored, _ = load_runtime(output)
    assert not any(p.requires_grad for p in restored.parameters())
