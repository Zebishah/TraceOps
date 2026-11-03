# Fine-tuning hardening and release runbook

Branch: `feat/production-finetuning-hardening`.

This phase hardens the training and inference implementation. A production model is a separate outcome: it requires reviewed incident data, a competitive held-out evaluation against Groq, an authorized signature, and deployment verification on the target hardware. Passing code tests does not establish model accuracy.

The existing Groq classifier stays selected unless explicitly changed. No database migration, financial rule, approval decision, n8n workflow, schedule, or voice endpoint is changed by this phase.

## Supported and verified scope

- CPU environment: Linux x86-64, Python 3.12, separately locked dependencies.
- Default training model: `Qwen/Qwen2.5-0.5B-Instruct`.
- Pinned verification revision: `7ae557604adf67be50417f59c2c2f167def9a775`.
- Training: supervised response-only LoRA, configurable adapter size/learning rate, validation selection, early stopping, resumable optimizer/RNG checkpoints.
- QLoRA: shared explicit NF4 loading configuration for training and serving. CUDA hardware execution remains unverified in this environment. The CPU lock intentionally does not provide a CUDA PyTorch build.
- Serving: one persistent model child per API worker, authenticated requests, pre-parse body limits, hard generation deadlines, process recovery, readiness, and Prometheus metrics.
- Production activation: signed, artifact-bound release plus the matching release ID in the main backend.
- Data source in automated verification: synthetic demo examples. No real reviewed dataset or live Groq baseline was supplied here. No production adapter is approved by those checks.

## What each changed file does

| File | Responsibility |
| --- | --- |
| `backend/src/ops_pilot/finetuning/dataset.py` | Deduplication, deterministic group splits, order-independent dataset identity, split hashes, overlap and duplicate checks across all splits. |
| `backend/src/ops_pilot/finetuning/quality.py` | Strict evaluation/review records, confusion matrices, per-class precision/recall/F1, safety metrics, paired comparison and promotion policy. |
| `backend/finetuning/prepare_dataset.py` | Preparation CLI; can emit an explicitly unapproved review template. |
| `backend/finetuning/train_classifier.py` | Actual adapter optimization, pinned model/tokenizer, checkpoints, resume validation, best-validation adapter selection and checksummed final manifest. |
| `backend/finetuning/artifacts.py` | Shared loading configuration, pinned references, file hashing, verification, atomic JSON writes and inference-only packaging. |
| `backend/finetuning/model_runtime.py` | Loads the verified base/adapter pair with the recorded loading settings; bounded deterministic generation and strict label validation. |
| `backend/finetuning/process_worker.py` | Model child process, IPC, hard deadlines, forced termination, graceful shutdown and recovery. |
| `backend/finetuning/http_limits.py` | Limits JSON bodies before parsing, including chunked requests and upload timeouts. |
| `backend/finetuning/serve_classifier.py` | Private FastAPI worker, signed production boot, token checks, single active prediction, health and metrics. |
| `backend/finetuning/evaluate_classifier.py` | Evaluates adapter/Groq/base on verified validation or test splits; saves case evidence and readable summary metrics. |
| `backend/finetuning/run_experiments.py` | Sequential reproducible model/rank/learning-rate experiments; selection uses validation only. |
| `backend/finetuning/examples/experiments.cpu.json` | Starting CPU experiment plan with pinned model revisions; not evidence that those settings are optimal. |
| `backend/finetuning/package_artifact.py` | Copies only verified inference files; excludes checkpoints and optimizer state. |
| `backend/finetuning/release.py` | Offline Ed25519 key generation/approval and public-key-only worker verification. |
| `backend/finetuning/verify_qwen.py` | Repeats actual Qwen training, reload, base/adapter validation and authenticated HTTP serving checks on synthetic data. |
| `backend/finetuning/pyproject.toml`, `uv.lock` | Separate frozen CPU dependency graph. The normal API lock remains unchanged. |
| `backend/finetuning/requirements.txt` | Legacy/manual GPU-environment dependency list; CPU reproducibility uses the separate lock. |
| `backend/finetuning/worker.env.example` | Production worker settings template. Actual `worker.env` is ignored. |
| `backend/src/ops_pilot/ai/finetuned_classifier.py` | Worker client, expected-release header check, telemetry and explicit unavailable confidence. |
| `backend/src/ops_pilot/ai/incident_classifier.py` | Opt-in selection, existing Groq fallback and classification/fallback logs. |
| `backend/src/ops_pilot/core/config.py` | Requires an approved release ID when selecting the adapter in production. |
| `backend/src/ops_pilot/core/logging.py` | Includes bounded classifier telemetry fields in existing JSON logs. |
| `backend/src/ops_pilot/schemas/incident_classification.py`, `schemas/incidents.py`, `workflows/incident/state.py`, `evaluation/classification.py` | Carry and validate unavailable confidence as `null` rather than a fabricated numeric score. |
| `frontend/lib/product/contracts.ts`, `frontend/components/workspace/incidents.tsx`, `frontend/components/workspace/intelligence.tsx` | Accept nullable confidence and display `Unavailable`; numeric displays retain their behavior. |
| `frontend/tests/classification-confidence.test.mts` | Covers nullable and existing numeric confidence. |
| `backend/tests/test_finetuning_quality.py`, `test_finetuning_artifacts.py`, `test_finetuning_process.py`, `finetuning_helpers.py` | Tests for quality gates, signatures, tampering, packaging, deadlines, cancellation and dead-child recovery. Fixtures are artificial unit-test evidence only. |
| Existing classifier/dataset/training/incident API tests | Default routing, release mismatch, auth, unavailable confidence, real training and resumed/uninterrupted equivalence. |
| `.github/workflows/backend-ci.yml` | API checks, frozen CPU adapter tests, frontend confidence contract and optional real-Qwen verification. |
| `.gitignore`, `backend/.env.example` | Private output exclusions and release-ID configuration. |

## Working directory and isolated installation

From the repository root, select this branch with `git switch feat/production-finetuning-hardening`. Run all commands below from **`ops-pilot/backend`** unless explicitly stated otherwise.

```bash
uv sync --frozen --group dev
uv sync --project finetuning --frozen
```

The API uses `backend/.venv`. Training/serving uses `backend/finetuning/.venv`. Keep both environments separate. Commands below use `--frozen` to preserve the training lock.

For CUDA QLoRA, create a separate hardware-specific environment with an appropriate CUDA PyTorch build, the pinned ML requirements and `bitsandbytes==0.50.2`. Validate that environment on the target GPU and retain its complete lock/build identity. Do not use the CPU lock and assume it enables CUDA. The current QLoRA compute dtype is conservatively float32; GPU throughput/precision tuning needs hardware validation.

## Dataset preparation and review

Use de-identified JSONL records with `title`, `description`, `category`, `priority`, and `group_id`. Categories: payment, account, access, data, integration, system, security, other. Priorities: low, medium, high, critical.

Related incidents and paraphrases must share a group ID. Use opaque identifiers. Review ambiguity, category definitions and severity with a domain owner. Existing AI-generated labels must be treated as draft labels, not human approval. Validation checks structure and consistency; it cannot determine whether labels are correct or whether all identifying information was removed.

```bash
uv run --project finetuning --frozen python -m finetuning.prepare_dataset --input finetuning/data/reviewed.jsonl --output finetuning/data/prepared --review-template finetuning/data/review.json
```

The review template starts with `source=unreviewed`, blank reviewer, null review timestamp and false approval/de-identification flags. An actual reviewer must complete it truthfully after inspecting the dataset:

- `dataset_sha256`: leave the prepared dataset fingerprint unchanged.
- `source`: `reviewed_incidents` only for real incident records that were reviewed; synthetic examples remain `synthetic`.
- `reviewer`: accountable operator/reviewer identifier.
- `reviewed_at`: actual ISO timestamp with timezone.
- `labels_approved`: true only after label review.
- `deidentified`: true only after checking and removing identifying data.

Changing data requires preparing new splits and obtaining a matching review. Splits are grouped, not automatically stratified: inspect category/priority counts and report supports. Default promotion requires at least 200 independent held-out groups; 200 total source records will not satisfy that after splitting. Never commit private records, review evidence, signing keys, adapters or reports.

## Train and resume

```bash
uv run --project finetuning --frozen python -m finetuning.train_classifier --data finetuning/data/prepared --output finetuning/runs/candidate --model Qwen/Qwen2.5-0.5B-Instruct --revision 7ae557604adf67be50417f59c2c2f167def9a775 --device cpu --epochs 3 --rank 8 --alpha 16 --learning-rate 0.0002
```

If no Hub revision is supplied, training resolves and records an exact commit before loading. Production artifacts require a full pinned Hub revision. Local base models use content hashes and are suitable for tests, not production release approval.

Training fails on edited splits, group overlap, duplicate incident text across splits, invalid budgets, non-finite loss/gradients and nonempty output directories without explicit resume. Full prompt/answer sequences are checked against the model context. The inference input limit reserves 64 answer tokens: default 1,024 training tokens produces a 960-token input limit.

Checkpoints retain adapter/tokenizer, optimizer tensors, Torch RNG, epoch position, shuffled-order seed, data identity and training settings. Mid-epoch resume preserves the next unprocessed group. Periodic progress checkpoints and validated checkpoints have distinct names. State uses `torch.load(..., weights_only=True)` after checksum validation. Resume only your trusted local checkpoints.

Read the path in `finetuning/runs/candidate/latest_checkpoint.json`, then:

```bash
uv run --project finetuning --frozen python -m finetuning.train_classifier --data finetuning/data/prepared --output finetuning/runs/candidate --model Qwen/Qwen2.5-0.5B-Instruct --revision 7ae557604adf67be50417f59c2c2f167def9a775 --device cpu --epochs 3 --rank 8 --alpha 16 --learning-rate 0.0002 --resume-from /absolute/path/to/checkpoint
```

Resume settings and data must match. Keep the original output/checkpoint directory together. The final root adapter is copied from the best observed validation-loss checkpoint, rather than always from the final update. Default patience is two validations without improvement; `--patience 0` disables early stopping. `--max-steps 1` checks execution mechanics and is not a meaningful training-quality run.

## Experiments and model selection

```bash
uv run --project finetuning --frozen python -m finetuning.run_experiments --config finetuning/examples/experiments.cpu.json --data finetuning/data/prepared --output finetuning/runs/experiments --device cpu
```

Each candidate records its pinned model, rank, alpha, dropout, learning rate, epochs, token budget and seed. Add other compatible base models with their own full revisions and enough hardware memory. The runner uses subprocess argument lists, not shell interpolation.

Candidates are evaluated only on validation data. Selection prioritizes fewer critical misses, fewer high-risk downgrades, higher joint accuracy, higher category macro F1, then lower P95 latency. Reports with infrastructure failures or no usable predictions are ineligible. `selected.json` always says `production_approved=false`. Do not repeatedly tune against test results. Evaluate the selected candidate on the held-out test set after the choice is fixed.

## Held-out evaluation and baseline

```bash
uv run --project finetuning --frozen python -m finetuning.evaluate_classifier --backend adapter --adapter finetuning/runs/candidate --input finetuning/data/prepared/test.jsonl --split test --output finetuning/reports/adapter-test.json --device cpu
uv run python -m finetuning.evaluate_classifier --backend groq --input finetuning/data/prepared/test.jsonl --split test --output finetuning/reports/groq-test.json
```

Groq uses the existing backend environment/API key and consumes provider quota. `--backend base --adapter ...` evaluates the same pinned base model without the adapter for experiments; it is not a Groq baseline and cannot satisfy promotion.

The evidence JSON contains hashed case/group IDs, expected/predicted labels, bounded error categories and latency. Its `.summary.json` companion includes confusion matrices, precision/recall/F1 by class, macro F1, overall accuracies, independent group counts, invalid outputs, infrastructure failures, safety errors, P50/P95 latency and peak RSS. Reports do not store incident text. A hash is an identity mechanism, not a substitute for de-identifying the input data.

Invalid predictions are counted as errors, never silently dropped. A critical miss means either category or priority is wrong for an expected critical incident. High-risk downgrades include missing outputs or lower predicted severity for high/critical incidents. Peak RSS includes the parent and model child; measurements depend on hardware and concurrent workload.

## Package the selected adapter

```bash
uv run --project finetuning --frozen python -m finetuning.package_artifact --input finetuning/runs/candidate --output finetuning/adapters/candidate
```

Only manifest-listed files and the artifact manifest are copied. Dataset files, checkpoints and optimizer state stay outside the inference package. File checksums, prompt version, base-model revision and quantization settings are verified on load. Do not retrain inside a deployed artifact directory; deploy immutable versioned packages.

## Promotion policy and signing

Default policy:

| Check | Requirement |
| --- | --- |
| Dataset | Real reviewed incidents, approved labels, de-identification attestation matching dataset hash. |
| Held-out evidence | Identical adapter/Groq test cases, groups and labels, bound to the artifact's test-file hash and expected-case fingerprint. |
| Sample size | At least 200 test examples and 200 independent groups. |
| Coverage | At least 10 per category; at least 10 per non-critical priority; at least 20 critical examples. |
| Quality | Joint accuracy at least 0.90; category and priority macro F1 at least 0.85. |
| Baseline | No joint-accuracy regression; no category recall decline greater than 0.05; no increase in high-risk downgrades. |
| Critical incidents | Zero critical misses. |
| Invalid output | At most 1%. |
| Infrastructure | Zero adapter or baseline infrastructure failures. |
| Resources | P95 at most 8 seconds and peak RSS at most 6,144 MiB. |

These are explicit starting acceptance criteria, not a universal guarantee of production quality. A domain owner should approve criteria suitable for the actual risk and hardware. A custom `--policy` JSON is included in the signed release; changing policy or model requires a new approval. Statistical uncertainty, deployment load tests and domain acceptance remain part of a real release decision.

Create signing keys on the approval machine:

```bash
uv run --project finetuning --frozen python -m finetuning.release generate-key --private-file finetuning/keys/release.private.key --public-file finetuning/keys/release-public.txt
```

The private key is created with owner-only permissions. Keep it offline; the serving worker receives only the base64 public key. Keys/evidence are ignored by Git. Approval is an explicit operator action after reviewing the reports:

```bash
uv run --project finetuning --frozen python -m finetuning.release approve --adapter finetuning/adapters/candidate --adapter-report finetuning/reports/adapter-test.json --baseline-report finetuning/reports/groq-test.json --review finetuning/data/review.json --private-key-file finetuning/keys/release.private.key --output finetuning/reports/release.json
```

It refuses synthetic/unreviewed evidence, failed policy, mismatched artifacts/test sets and future review timestamps. It prints a release ID only after signing. Evidence/report origin ultimately depends on the accountable signer; software cannot independently prove that a person reviewed real records. No script auto-approves a model after training.

## Serve and activate

Copy `finetuning/worker.env.example` to the ignored `finetuning/worker.env` and fill the verified package path, release path, public key and a separate random serving token. Default worker mode is production and refuses startup without a valid signature.

```bash
uv run --project finetuning --frozen uvicorn finetuning.serve_classifier:app --env-file finetuning/worker.env --host 127.0.0.1 --port 8001 --workers 1
```

Keep the worker private. A remote deployment needs HTTPS, network restrictions and adequate memory. Cache the pinned base-model files before setting `HF_HUB_OFFLINE=1`. A package contains adapters/tokenizer, not a full replacement for the base model. CPU float32 base weights alone are roughly 2 GB for the configured model; use measured peak memory plus headroom when sizing the worker.

Configure the main backend only after worker readiness and release verification:

```dotenv
INCIDENT_CLASSIFIER_BACKEND=finetuned
FINETUNED_CLASSIFIER_URL=http://127.0.0.1:8001/classify
FINETUNED_CLASSIFIER_TOKEN=the-same-random-serving-token
FINETUNED_CLASSIFIER_RELEASE_ID=the-release-id-printed-by-approval
FINETUNED_CLASSIFIER_TIMEOUT_SECONDS=10
FINETUNED_CLASSIFIER_FALLBACK_ENABLED=true
```

Production backend configuration requires the expected release ID. Every accepted worker response carries that ID; a mismatch triggers failure/fallback. Localhost refers to the current host, so use a private HTTPS address between separate machines. The configured client timeout should exceed the worker deadline and network overhead.

A developer can explicitly set `CLASSIFIER_ENVIRONMENT=development` to run an unapproved adapter locally. It returns `X-Classifier-Release: development`, which cannot match the production backend's required 64-character release ID.

## Runtime protection, monitoring and rollback

- JSON bodies are bounded to 64 KiB before parsing, including actual chunked size, with a five-second upload deadline.
- Only one generation is admitted per worker; busy/unready requests return 503.
- Default generation deadline is eight seconds. Timeout terminates the child process, returns 504, and starts a recovery process. Cancelling an active request also stops its computation.
- `/health/live` reports API liveness. `/health/ready` returns 503 until a live model process is ready; polling or a request can trigger recovery after a dead child. Supervise/restart the API process if recovery repeatedly fails.
- Authenticated `/metrics` exposes readiness, child peak RSS, request outcomes, latency histogram and category/priority prediction counts. Counters reset on restart; aggregate replicas in the monitoring system.
- Invalid rate: invalid outcomes divided by completed model attempts. Monitor timeouts/errors/busy separately. Inspect prediction distribution for drift; a changed distribution is a signal for review, not proof that predictions are wrong.
- Backend JSON logs contain `incident_classification_requested`, `classifier_worker_prediction` and `finetuned_classifier_fallback_to_groq`, with bounded telemetry. Use fallback events / classification requests to monitor fallback rate. No incident text, credentials or generated raw output is added to classifier logs.
- Rollback: set `INCIDENT_CLASSIFIER_BACKEND=groq` and restart the API. Keep the previous immutable package/release available. Financial/approval guards remain in the existing workflow.

## Confidence API change

Adapter classifications now return `confidence: null`; investigation responses carry `classification_confidence: null`. This means unavailable/uncalibrated. Existing numeric Groq confidence remains supported and is provider-reported, not independently calibrated by this phase. The repository frontend accepts null and displays `Unavailable`. Other API clients must also accept null instead of formatting it as a percentage. Historical numeric records are not migrated.

## Verification and its limits

From `ops-pilot/backend`:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -q
uv run --project finetuning --frozen pytest -q tests/test_finetuning_training.py tests/test_classifier_worker.py tests/test_finetuning_artifacts.py tests/test_finetuning_quality.py tests/test_finetuning_process.py
uv run --project finetuning --frozen python -m finetuning.verify_qwen --output finetuning/runs/qwen-verification
```

The normal suite needs a disposable local Redis for existing integration tests. External-service opt-ins retain their existing requirements. The separate CPU test performs actual optimization, best-checkpoint selection, save/reload and resumed-vs-uninterrupted comparison. Process tests exercise a genuinely hung child, cancellation and process death.

The Qwen command downloads the pinned model, runs one optimizer step on synthetic data, reloads the adapter, measures all validation cases for adapter and unmodified base, then checks the actual authenticated HTTP worker and metrics. It writes `verification.json` with `production_approved=false`. Poor predictions/invalid JSON are reported honestly. This establishes executable mechanics and error handling, not production accuracy. The optional manual CI input `verify_qwen=true` repeats it; ordinary CI uses the tiny local model to avoid a 1 GB download on every push.

No reviewed production corpus, live Groq comparison, CUDA run, production deployment or production promotion is claimed by these code checks.

## Measured synthetic verification in this phase

The committed `docs/finetuning-verification.json` records the actual pinned Qwen CPU run and a two-candidate experiment smoke run. Each candidate received only one optimizer update. These are implementation checks, not a training recommendation or a benchmark on real incidents.

- Qwen adapter validation: four independent synthetic examples, 0% category accuracy, 25% priority accuracy, 0% joint accuracy, one invalid output and no infrastructure errors. No critical examples were present, so zero critical misses supplies no evidence of critical-incident safety.
- Adapter validation p95 was about 3.96 seconds; measured peak RSS was about 3312 MiB on this host. These measurements do not establish production capacity or service-level guarantees.
- Actual HTTP serving accepted three schema-valid predictions, rejected one invalid prediction, and passed authentication and metrics checks. Schema-valid does not mean correctly classified.
- The experiment command trained rank-4 and rank-8 candidates, evaluated validation only, and wrote a rank-4 selection with `production_approved=false`. Both had 0% joint accuracy after their single update.
- The release remains unapproved. Reviewed data, proper training/model selection, the untouched paired Groq test, and target-hardware verification are still required.
