# Synthetic incident dataset v1

This is an AI-authored English training corpus for OpsPilot's category/priority classifier. No customer records, user-provided demo incidents or external datasets were copied. It is suitable for learning, reproducible training experiments and synthetic validation. It is not human-reviewed production evidence and does not authorize switching the production classifier.

## Files

- `backend/finetuning/examples/incidents.synthetic-v1.jsonl`: 512 ready-to-parse labeled records.
- `backend/finetuning/examples/incidents.synthetic-v1.provenance.json`: fingerprints, counts, recommended split seed, limitations and explicit synthetic/unapproved status.
- `backend/tests/test_synthetic_incident_dataset.py`: structural, grouping, split-coverage, fingerprint and quoted-instruction target checks.

Each record uses the existing schema: title, description, category, priority and group_id. Metadata such as group IDs is not supplied to the model as incident text.

## What the numbers mean

There are 64 underlying scenario families, eight per category. Each family has four separately authored impact/severity scenarios and two title/format variants per scenario. Thus there are 256 authored severity scenarios represented by 512 records, not 512 independent real incidents. The second version reuses the factual situation with a different title/report format; it is not an independently observed incident.

| Category | Records | Scenario families |
| --- | ---: | ---: |
| payment | 64 | 8 |
| account | 64 | 8 |
| access | 64 | 8 |
| data | 64 | 8 |
| integration | 64 | 8 |
| system | 64 | 8 |
| security | 64 | 8 |
| other | 64 | 8 |

Each priority has 128 records. Each category/priority combination has 16 records. Thirty-two variants contain quoted instructions requesting deliberately incorrect labels; the target still follows the incident facts. Their paired versions stay together. These cases are for robustness experiments, not a security guarantee.

The recommended fixed seed is **1687**. It was chosen for label coverage before any model predictions, not tuned using model accuracy. With the existing grouped splitter:

| Split | Records | Families | Category/priority combinations present |
| --- | ---: | ---: | ---: |
| train | 368 | 46 | 32 |
| validation | 72 | 9 | 32 |
| test | 72 | 9 | 32 |

All wording and severity variants of one family share the same group. A payment-double-capture family, for example, cannot appear in both training and testing. Group and duplicate-input overlap are checked by the existing preparation/verification code.

## Label assumptions

The labels follow the existing classifier prompt:

- Payment: billing, charged amounts, refunds and settlement.
- Account: profile, membership and account-lifecycle administration.
- Access: authentication or legitimate permissions being denied.
- Data: missing, duplicate, stale, incorrectly mapped or corrupted records.
- Integration: a specifically identified external API/webhook/connector failure.
- System: internal application, job, capacity or infrastructure failure.
- Security: suspected or confirmed compromise, unauthorized access or related security reports.
- Other: physical operational problems outside those software/account/billing categories.

The explicit reported mechanism is the main category; impact determines priority. A failed external shipping API is integration even though dispatch is affected. A contained security exposure may be high, while active severe ongoing compromise is critical. An isolated inconvenience is low; a limited disruption with a workable alternative is medium; a blocked important workflow/material loss is high; widespread service outage, major data loss or active severe compromise is critical.

The same incident family intentionally spans different priorities: a duplicate receipt display without extra money moving is different from active platform-wide duplicate captures. Human reviewers may disagree on borderline operational labels. These assumptions must be reviewed against your real business before production use. Physical platform-wide operational outages are used for other/critical; the underlying software remains healthy.

## Prepare the files

From **ops-pilot/backend**:

```bash
uv sync --frozen --group dev
uv run --frozen python -m finetuning.prepare_dataset --input finetuning/examples/incidents.synthetic-v1.jsonl --output finetuning/data/synthetic-v1 --seed 1687
```

This writes train/validation/test JSONL, their question-and-answer copies, and manifest.json. The output folder must be empty or absent. If you already prepared this exact corpus, reuse it; do not overwrite a dataset used by an existing experiment.

Keep the source/provenance files together. The generic optional --review-template produces an unreviewed template; it must never be changed to reviewed_incidents for this corpus. Human inspection of synthetic records does not turn them into real customer incidents.

## Train and inspect validation results

From **ops-pilot/backend**:

```bash
uv sync --project finetuning --frozen
uv run --project finetuning --frozen python -m finetuning.train_classifier --data finetuning/data/synthetic-v1 --output finetuning/adapters/synthetic-v1 --model Qwen/Qwen2.5-0.5B-Instruct --revision 7ae557604adf67be50417f59c2c2f167def9a775 --device cpu --epochs 3 --max-tokens 1024
uv run --project finetuning --frozen python -m finetuning.evaluate_classifier --backend adapter --adapter finetuning/adapters/synthetic-v1 --input finetuning/data/synthetic-v1/validation.jsonl --output finetuning/reports/synthetic-v1-validation.json --device cpu
```

The model/tokenizer download needs internet. CPU training can be slow and requires adequate free memory. The dataset was validated mechanically, but downloading the pinned Qwen tokenizer in this authoring session failed because huggingface.co could not be reached. Exact per-record Qwen token lengths were not verified here. The trainer checks the actual tokenized length and refuses overlong examples instead of truncating them.

To check mechanics first, use a different output folder such as finetuning/adapters/synthetic-v1-smoke and add --max-steps 8. A short smoke run is not a substitute for proper training. Output directories must be empty; the existing resume procedure is documented in [the training runbook](finetuning-production-hardening.md).

Tune only with training/validation. Keep test.jsonl untouched until you have chosen a final candidate. Then compare the adapter and Groq on that same synthetic test file using evaluate_classifier. Groq uses your existing backend credentials and provider quota. Any result is a synthetic benchmark and must be described that way.

## What remains outside this dataset

- No real-world accuracy, calibration or improvement over Groq is claimed.
- Label balance was designed for coverage; real incident frequencies will differ.
- Only 64 families are represented. More title variants do not create more independent evidence.
- Natural writing styles, unknown failure types, multilingual/Urdu input and real production noise need separate checks.
- The production release gate still requires real reviewed incidents, minimum independent test coverage, paired Groq comparison and runtime checks. This synthetic corpus intentionally cannot satisfy its real-data requirement.
- No model training or production deployment was performed as part of creating the dataset.

The practical next step is to run the preparation command, train an experimental adapter, and inspect its validation report. Keep INCIDENT_CLASSIFIER_BACKEND=groq in production.
