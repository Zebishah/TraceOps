import json

import pytest

from ops_pilot.finetuning.dataset import (
    IncidentExample,
    load_examples,
    split_examples,
    training_record,
    write_splits,
)


def example(index=0, **overrides):
    return IncidentExample.model_validate(
        {
            "title": f"Payment incident {index}",
            "description": f"Two charges for order {index}",
            "category": "payment",
            "priority": "high",
            "group_id": f"group-{index}",
            **overrides,
        }
    )


def test_splits_are_deterministic_and_keep_related_cases_together():
    records = [example(index) for index in range(20)]
    records += [example(99, group_id="group-1")]
    first = split_examples(records)
    assert first == split_examples(list(reversed(records))) or {
        k: {e.group_id for e in v} for k, v in first.items()
    } == {k: {e.group_id for e in v} for k, v in split_examples(list(reversed(records))).items()}
    groups = {k: {e.group_id for e in v} for k, v in first.items()}
    assert not groups["train"] & groups["test"]
    assert not groups["train"] & groups["validation"]
    assert not groups["validation"] & groups["test"]
    assert sum(len(v) for v in first.values()) == len(records)


def test_duplicate_examples_are_removed(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text(example().model_dump_json() + "\n" + example().model_dump_json())
    assert len(load_examples(path)) == 1


@pytest.mark.parametrize("overrides", [{"priority": "low"}, {"group_id": "other"}])
def test_conflicting_duplicates_fail(tmp_path, overrides):
    path = tmp_path / "data.jsonl"
    path.write_text(example().model_dump_json() + "\n" + example(**overrides).model_dump_json())
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        load_examples(path)


def test_training_record_does_not_teach_invented_confidence():
    record = training_record(example())
    answer = json.loads(record["completion"][0]["content"])
    assert answer == {"category": "payment", "priority": "high"}
    assert "untrusted" in record["prompt"][0]["content"]


def test_small_dataset_and_invalid_fractions_rejected():
    with pytest.raises(ValueError, match="three"):
        split_examples([example()])
    for fraction in [0, 1, float("nan"), float("inf")]:
        with pytest.raises(ValueError, match="fractions"):
            split_examples([example(i) for i in range(10)], test_fraction=fraction)


def test_generated_datasets_are_not_overwritten(tmp_path):
    output = tmp_path / "prepared"
    write_splits(examples=[example(i) for i in range(20)], output=output)
    manifest = json.loads((output / "manifest.json").read_text())
    assert sum(manifest["counts"].values()) == 20
    assert len(manifest["dataset_sha256"]) == 64
    assert (output / "test.sft.jsonl").exists()
    with pytest.raises(ValueError, match="never overwritten"):
        write_splits(examples=[example(i) for i in range(20)], output=output)
