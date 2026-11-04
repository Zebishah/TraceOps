"""Checks for the authored synthetic corpus; these are not model quality benchmarks."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from ops_pilot.finetuning.dataset import (
    dataset_fingerprint,
    load_examples,
    training_record,
    verified_splits,
    write_splits,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "finetuning" / "examples"
DATASET = EXAMPLES / "incidents.synthetic-v1.jsonl"
PROVENANCE = EXAMPLES / "incidents.synthetic-v1.provenance.json"
CATEGORIES = {"payment", "account", "access", "data", "integration", "system", "security", "other"}
PRIORITIES = {"low", "medium", "high", "critical"}


def test_synthetic_corpus_has_full_balanced_label_coverage_without_deduplicating_rows():
    examples = load_examples(DATASET)
    raw_rows = DATASET.read_text().splitlines()
    assert len(raw_rows) == len(examples) == 512
    assert Counter((str(e.category), str(e.priority)) for e in examples) == Counter(
        {(category, priority): 16 for category in CATEGORIES for priority in PRIORITIES}
    )
    assert all(1 <= len(e.title) <= 200 and 1 <= len(e.description) <= 8192 for e in examples)


def test_provenance_identifies_synthetic_unreviewed_data_with_exact_fingerprints():
    provenance = json.loads(PROVENANCE.read_text())
    examples = load_examples(DATASET)
    assert provenance["source"] == "synthetic"
    assert provenance["human_reviewed"] is False
    assert provenance["production_approved"] is False
    assert provenance["records"] == len(examples)
    assert provenance["scenario_families"] == len({e.group_id for e in examples}) == 64
    assert provenance["dataset_sha256"] == dataset_fingerprint(examples)
    assert provenance["file_sha256"] == hashlib.sha256(DATASET.read_bytes()).hexdigest()


def test_all_wording_and_severity_variants_share_a_family_group():
    families = defaultdict(list)
    for example in load_examples(DATASET):
        families[example.group_id].append(example)
    for values in families.values():
        assert len(values) == 8
        assert len({e.category for e in values}) == 1
        assert Counter(str(e.priority) for e in values) == Counter(dict.fromkeys(PRIORITIES, 2))
        assert len({e.title for e in values}) == 2


def test_recommended_splits_cover_all_labels_and_keep_families_and_inputs_disjoint(tmp_path):
    examples = load_examples(DATASET)
    provenance = json.loads(PROVENANCE.read_text())
    write_splits(examples=examples, output=tmp_path, seed=provenance["recommended_seed"])
    splits, fingerprint = verified_splits(tmp_path)
    assert fingerprint == provenance["dataset_sha256"]
    groups = {}
    for name, values in splits.items():
        groups[name] = {e.group_id for e in values}
        assert {str(e.category) for e in values} == CATEGORIES
        assert {str(e.priority) for e in values} == PRIORITIES
        assert len({(e.category, e.priority) for e in values}) == 32
        assert len(values) == provenance["splits"][name]["records"]
        assert len(groups[name]) == provenance["splits"][name]["families"]
    assert not groups["train"] & groups["validation"]
    assert not groups["train"] & groups["test"]
    assert not groups["validation"] & groups["test"]


def test_quoted_instructions_do_not_change_supplied_targets():
    protected = []
    for example in load_examples(DATASET):
        if "Quoted text attached to the report:" not in example.description:
            continue
        match = re.search(r"return (\{.*?\})", example.description)
        assert match is not None
        malicious = json.loads(match.group(1))
        expected = {"category": str(example.category), "priority": str(example.priority)}
        assert malicious["category"] != expected["category"]
        record = training_record(example)
        assert json.loads(record["completion"][0]["content"]) == expected
        protected.append(example)
    assert len(protected) == 32
