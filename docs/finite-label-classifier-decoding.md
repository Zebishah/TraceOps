# Finite-label classifier output fix

## Confirmed failure

The synthetic-v1 adapter emitted valid JSON such as `{"category":"storage","priority":"high"}`. Storage is not an allowed category, so the existing strict validator correctly rejected it. There is no malformed-JSON evidence in those three diagnostic outputs.

The new finite-labels-v1 generation policy permits exactly the 32 canonical JSON objects formed from the eight categories and four priorities. It filters possible next tokens during generation and permits an end token only after a complete valid answer. It does not translate storage into system or choose labels with keyword rules. The model still decides which allowed category and priority to output, so a semantically incorrect data/system choice is still possible.

## Compatibility and identity

- Existing artifacts without output_policy retain unconstrained generation. Their fingerprints and signed release bindings remain identical.
- Newly trained artifacts record output_policy=finite-labels-v1.
- Existing trained weights can be copied into a new constrained package with constrain_classifier. No training or model-weight modification is needed.
- The copy records derived_from_artifact_sha256 and a different artifact fingerprint. The original package, checkpoints, tokenizer and reports are preserved.
- Conversion validates all 32 label token paths using the package's saved tokenizer, without downloading a model or loading its weights. Unsupported tokenizers, EOS settings or insufficient answer budgets fail explicitly.
- Loading validates the decoder before loading the base-model weights. Normal strict output validation, context/body limits, process deadlines and recovery remain active.
- A changed output policy requires its own evaluation and signed production release. An old release cannot authorize the derived artifact.
- No database schema, incident workflow, Groq default, frontend contract, signing policy or production environment setting is changed.

## Apply to your already trained adapter

From your local **ops-pilot/backend** directory, after selecting this PR's branch:

```bash
uv sync --project finetuning --frozen
uv run --project finetuning --frozen python -m finetuning.constrain_classifier --source finetuning/adapters/synthetic-v1 --output finetuning/adapters/synthetic-v1-constrained
```

The source must be a valid existing adapter package with its tokenizer files. The destination must not exist. The command prints the original and derived artifact IDs. Do not delete or overwrite your original adapter or evaluation reports. No new API key or environment variable is needed for conversion.

Start by checking the new package on validation:

```bash
uv run --project finetuning --frozen python -m finetuning.evaluate_classifier --backend adapter --adapter finetuning/adapters/synthetic-v1-constrained --input finetuning/data/synthetic-v1/validation.jsonl --output finetuning/reports/synthetic-v1-constrained-validation-diagnostic.json --device cpu --timeout-seconds 30
```

Then, if you want to confirm the diagnosed unsupported-label failures on the previously inspected test set:

```bash
uv run --project finetuning --frozen python -m finetuning.evaluate_classifier --backend adapter --adapter finetuning/adapters/synthetic-v1-constrained --input finetuning/data/synthetic-v1/test.jsonl --output finetuning/reports/synthetic-v1-constrained-test-diagnostic.json --device cpu --timeout-seconds 30
```

The inspected test set is now diagnostic evidence, not a fresh untouched benchmark for this fix. A later quality claim requires new independent held-out scenario families. A finite syntax constraint is not a solution for ambiguous synthetic labels or weak category/priority understanding.

Fish-compatible command to read the diagnostic test summary:

```bash
uv run --frozen python -c '
import json
from pathlib import Path
path = Path("finetuning/reports/synthetic-v1-constrained-test-diagnostic.summary.json")
report = json.loads(path.read_text())
fields = ["total", "category_accuracy", "priority_accuracy", "joint_accuracy", "invalid_outputs", "infrastructure_errors", "critical_misses", "high_risk_downgrades", "latency_p95_seconds"]
print(json.dumps({key: report[key] for key in fields}, indent=2))
'
```

Do not claim that invalid output or semantic error rates improved until the actual Qwen diagnostic run completes. CPU tiny-model tests verify the real Transformers constrained-generation path and conversion mechanics, not Qwen classification accuracy or CUDA execution.

## Files

| File | Responsibility |
| --- | --- |
| backend/finetuning/label_decoding.py | Immutable versioned label vocabulary, tokenizer checks and allowed next-token paths. |
| backend/finetuning/artifacts.py | Recorded decoding policy and derivation identity, preserving legacy fingerprints. |
| backend/finetuning/model_runtime.py | Initializes and applies the artifact's selected policy during generation. |
| backend/finetuning/train_classifier.py | Records the finite-label policy on newly trained artifacts. |
| backend/finetuning/constrain_classifier.py | Validates and copies an existing trained package into a new constrained package. |
| backend/tests/test_finite_label_decoding.py | Valid paths, forbidden outputs, EOS/budgets, legacy hashes and immutable conversion. |
| backend/tests/test_finetuning_training.py | Actual tiny-model training, constrained generation, real-tokenizer conversion and resume equivalence. |
| backend/tests/test_finetuning_artifacts.py | Verifies that an older signed release cannot authorize a changed policy. |
| .github/workflows/backend-ci.yml | Runs finite-decoder tests in the frozen CPU environment and checks helper types. |
