# Voice AI and classifier fine-tuning: implementation phase

Branch: `feat/voice-ai-and-classifier-finetuning`, created from `main` at `b6e001d`.

> Training/serving follow-up: see [production hardening and release runbook](finetuning-production-hardening.md). It documents verified artifacts, signed releases, frozen CPU dependencies, hard deadlines and nullable confidence.

## What this phase adds

1. Authenticated recorded-audio transcription using Groq Whisper.
2. Authenticated English text-to-speech using Groq Orpheus (up to 200 characters).
3. Offline incident-classifier dataset preparation and supervised LoRA/QLoRA training.
4. A separate adapter inference worker and an optional backend client with Groq fallback.
5. Regression tests, an actual tiny-model training smoke test, and CI coverage.

This is recorded-audio voice I/O, not a continuous real-time conversation or SSE feature.
The training pipeline is implemented; a useful production classifier has NOT been trained or
shown to outperform the existing model. The committed 32-example dataset is synthetic demonstration
material, not sufficient evidence for production quality.

## Isolation and existing behavior

- Voice is disabled by default. Disabled requests return 503 after authorization.
- The incident classifier remains `groq` by default. Its existing prompt and output schema remain.
- No migration, financial rule, approval decision, investigation graph, n8n export, or recovery
  schedule changes are included.
- No new backend runtime dependencies or changes to `backend/uv.lock` are required.
- ML libraries belong to a separate environment. No models load in the production FastAPI process.
- Transcription does not create incidents or authorize actions. The UI must show the transcript,
  let the operator correct it and choose the customer, then submit through the existing incident API.
- No microphone recording, transcript, or synthesized audio is persisted by this feature.
  Audio/text is sent to Groq for processing; provider retention follows the provider/account policy.
- Voice routes use existing tenant membership and incident-creator roles: owner/admin/operator.
- Both routes share a Redis-backed per-user, per-organization rate limit and two process-local
  provider slots. Rate-limit infrastructure failures reject requests rather than allowing unlimited use.
- Request bodies are bounded before parsing, provider responses are bounded, redirects are disabled,
  and provider errors are returned without provider response text. Audio signatures identify containers;
  the provider performs actual decoding. This is not a complete media-file integrity validator.

## File-by-file map

| File | Purpose |
| --- | --- |
| `backend/src/ops_pilot/api/routes/voice.py` | Two new organization-scoped voice endpoints. |
| `backend/src/ops_pilot/schemas/voice.py` | Transcription response and bounded speech input. |
| `backend/src/ops_pilot/services/voice.py` | Groq requests, audio validation, timeouts, concurrency, rate limits. |
| `backend/src/ops_pilot/api/voice_limit.py` | Voice-only body limits before JSON/multipart parsing. |
| `backend/src/ops_pilot/api/router.py` | Registers the additive voice router. |
| `backend/src/ops_pilot/main.py` | Registers the voice-only body-limit middleware. |
| `backend/src/ops_pilot/core/config.py` | Validated opt-in voice and classifier settings. |
| `backend/src/ops_pilot/ai/finetuned_classifier.py` | Strict bounded HTTP client for the separate model worker. |
| `backend/src/ops_pilot/ai/incident_classifier.py` | Selects the optional adapter; preserves Groq as default/fallback. |
| `backend/src/ops_pilot/finetuning/__init__.py` | Lightweight training-data package. |
| `backend/src/ops_pilot/finetuning/dataset.py` | Reviewed labels, shared prompt, deduplication, grouped splits, SFT JSONL. |
| `backend/finetuning/__init__.py` | Offline tooling package, separate from deployed service initialization. |
| `backend/finetuning/prepare_dataset.py` | CLI for validation and train/validation/test preparation. |
| `backend/finetuning/train_classifier.py` | Actual PyTorch supervised training with LoRA or QLoRA and response-only loss. |
| `backend/finetuning/model_runtime.py` | Loads the adapter and validates generated category/priority JSON. |
| `backend/finetuning/serve_classifier.py` | Token-protected, single-model worker, bound to loopback by default. |
| `backend/finetuning/evaluate_classifier.py` | Measures category/priority/joint accuracy and invalid outputs. |
| `backend/finetuning/requirements.txt` | Optional pinned ML dependencies, outside the API lock. |
| `backend/finetuning/examples/incidents.demo.jsonl` | Synthetic examples for learning the workflow. |
| `backend/tests/test_voice.py` | Authorization, flags, audio/body limits, provider errors, TTS, rate-limit tests. |
| `backend/tests/test_finetuned_classifier.py` | Default routing, strict outputs, worker security and fallback tests. |
| `backend/tests/test_finetuning_dataset.py` | Deduplication, group isolation, deterministic splits, no overwrite tests. |
| `backend/tests/test_finetuning_training.py` | Optional real one-step LoRA training, adapter save/reload, no download. |
| `backend/tests/test_classifier_worker.py` | Worker credentials, output contract, sanitized failures. |
| `backend/.env.example` | Documents every new feature flag. |
| `.gitignore` | Ignores private datasets, adapters, reports, and the ML environment. |
| `.github/workflows/backend-ci.yml` | Adds disposable Redis for existing integration tests and a CPU LoRA smoke job. |

## Get the branch

Run from your local `ops-pilot` repository root:

```bash
git fetch origin
git switch --track origin/feat/voice-ai-and-classifier-finetuning
cd backend
uv sync --frozen --group dev
```

If the local branch already exists, switch to it instead of creating another tracking branch.

## Enable and test voice

Working directory for all commands below: `ops-pilot/backend`.
Keep your existing `.env` values. Add or update:

```dotenv
VOICE_ENABLED=true
VOICE_TTS_ENABLED=true
VOICE_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
VOICE_TTS_VOICE=troy
VOICE_TIMEOUT_SECONDS=30
VOICE_REQUESTS_PER_MINUTE=10
INCIDENT_CLASSIFIER_BACKEND=groq
```

Restart the backend:

```bash
uv run uvicorn ops_pilot.main:app --reload
```

In Swagger (`/docs`), log in using the existing authentication flow, authorize with the access
token, and select an organization you belong to. New endpoints:

- `POST /api/v1/organizations/{organization_id}/voice/transcriptions`
  accepts multipart `file` and optional two-letter `language` (for example `en` or `ur`).
  The file limit is 10 MiB; recognized containers are WAV, WebM, Ogg, FLAC, MP3, and MP4/M4A.
  Transcription quality and mixed-language recognition require testing with your recordings.
  Response example:

  ```json
  {"text":"Customer reports two charges.","model":"whisper-large-v3-turbo","requires_confirmation":true}
  ```

- `POST /api/v1/organizations/{organization_id}/voice/speech`
  accepts `{"text":"Investigation requires human review."}` and returns `audio/wav`.
  This phase uses the English model. It does not promise Urdu speech synthesis.
  Inputs longer than 200 characters are rejected; summaries are never silently truncated.

Use your existing `GROQ_API_KEY`. Provider model permissions/free quotas apply; do not assume
unlimited free usage. No live provider requests are part of the automated tests.
For emergency disablement, set `VOICE_ENABLED=false` and `VOICE_TTS_ENABLED=false`, then restart.

## Prepare a dataset without changing the database

Each JSONL record has exactly these fields:

```json
{"title":"Customer charged twice","description":"Two successful charges for one order.","category":"payment","priority":"high","group_id":"reviewed-case-001"}
```

Allowed categories: payment, account, access, data, integration, system, security, other.
Allowed priorities: low, medium, high, critical. Confidence is not a training target.
Paraphrases/related incidents must share `group_id`. Human-review the labels and de-identify data.
Do not add tenant data to Git. Keep private inputs under the ignored `finetuning/data/` directory.
No script exports production database records or uploads training data to a model hub.

Run the educational example:

```bash
uv run python -m finetuning.prepare_dataset --input finetuning/examples/incidents.demo.jsonl --output finetuning/data/demo
```

Outputs: `train.jsonl`, `validation.jsonl`, `test.jsonl`, equivalent `*.sft.jsonl` message records,
and `manifest.json` with counts, seed, and dataset hash. Duplicates are removed; conflicting labels
or duplicate records assigned to different groups fail. Existing output directories are not overwritten.
Splitting is group-based, not stratified: inspect category coverage before using a small dataset.
The training command consumes the validated records and constructs response-only token labels.

## Install the separate training environment

For a CPU learning experiment:

```bash
uv sync --project finetuning --frozen
```

This does not alter the normal API `.venv`, API requirements, or lock file. The frozen CPU environment is `finetuning/.venv`. A small model can run on CPU,
but full training/generation may be slow. CPU RAM requirements depend on model/context length.
Use a separate GPU environment for QLoRA; the CPU PyTorch build cannot perform CUDA training.
Install a matching CUDA PyTorch build, the requirements, and `bitsandbytes==0.50.2` there, then use
`--device cuda --qlora`. GPU/driver support must be checked for that machine. Do not train inside
the small deployed Render backend.

## Train, evaluate, and serve

Working directory: `ops-pilot/backend`. This downloads the selected base model, trains only its
LoRA adapter, and saves the adapter/tokenizer plus a training manifest. Check the base-model license.

```bash
finetuning/.venv/bin/python -m finetuning.train_classifier --data finetuning/data/demo --output finetuning/adapters/demo --model Qwen/Qwen2.5-0.5B-Instruct --device cpu --epochs 3
```

For a short execution smoke check, add `--max-steps 1` and use a different empty output directory.
That checks mechanics, not model quality. No training runs automatically when FastAPI starts.

Evaluate on untouched test examples and compare with the existing Groq classifier:

```bash
uv run python -m finetuning.evaluate_classifier --backend groq --input finetuning/data/demo/test.jsonl --output finetuning/reports/groq.json
finetuning/.venv/bin/python -m finetuning.evaluate_classifier --backend adapter --adapter finetuning/adapters/demo --input finetuning/data/demo/test.jsonl --output finetuning/reports/adapter.json
```

The Groq baseline command uses your existing API key and consumes provider quota. Other commands do not
send incidents to Groq. Check accuracy, invalid output counts, coverage, latency, and resource usage;
the script does not automatically enable or promote a model. The demo test set is far too small to
support a production improvement claim.

Start the separate worker only after a model passes your evaluation. Generate a separate random token
of at least 32 characters, and keep the same token in the API and worker environment:

```bash
export CLASSIFIER_ENVIRONMENT=development
export CLASSIFIER_ADAPTER_PATH="$PWD/finetuning/adapters/demo"
export CLASSIFIER_SERVING_TOKEN="your-separately-generated-random-secret-at-least-32-characters"
export CLASSIFIER_DEVICE=cpu
finetuning/.venv/bin/python -m finetuning.serve_classifier
```

The worker listens at `127.0.0.1:8001`, accepts `POST /classify`, and requires a bearer token.
It returns only `category` and `priority`, rejecting malformed model output. Its default input budget
is recorded in the artifact (960 input tokens with the default training budget); oversized prompts fail instead of silently discarding incident text. Never expose
this worker directly to the internet. Remote hosting requires HTTPS, network access restrictions,
and a reverse-proxy request-size limit. On separate hosts, localhost refers to each host itself.

To explicitly activate the adapter, configure the main backend:

```dotenv
INCIDENT_CLASSIFIER_BACKEND=finetuned
FINETUNED_CLASSIFIER_URL=http://127.0.0.1:8001/classify
FINETUNED_CLASSIFIER_TOKEN=the-same-secret-used-by-the-worker
FINETUNED_CLASSIFIER_TIMEOUT_SECONDS=10
FINETUNED_CLASSIFIER_FALLBACK_ENABLED=true
```

Restart the API. Invalid output, worker errors, or timeouts fall back to Groq by default.
Adapter classifications now use `confidence: null` to represent unavailable/uncalibrated confidence.
The repository frontend displays `Unavailable`. Production activation requires an approved signed
release and matching release ID; follow the hardening runbook. No financial authorization is derived
from confidence.
Rollback: set `INCIDENT_CLASSIFIER_BACKEND=groq` and restart. Approval/refund guards remain unchanged.

## Checks and what they prove

From `ops-pilot/backend`:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -q
```

Existing Redis integration tests need a local test Redis. External Postgres/live-AI tests retain their
existing opt-in requirements. The optional ML smoke test skips when training packages are absent.
To run it with real CPU training dependencies:

```bash
uv sync --project finetuning --frozen
finetuning/.venv/bin/python -m pytest -q tests/test_finetuning_training.py
```

The smoke test builds a tiny random local model/tokenizer, performs a real LoRA optimization step,
checks that trained adapter weights changed, saves it, and reloads it for inference. No base-model
download, real incident data, provider key, GPU, or external API is required. It establishes executable
training mechanics, not useful classifier performance. CI runs the same test in a separate job.

## Provider and framework references

- [Groq speech-to-text](https://console.groq.com/docs/speech-to-text)
- [Groq Orpheus text-to-speech](https://console.groq.com/docs/text-to-speech/orpheus)
- [Hugging Face PEFT](https://huggingface.co/docs/peft/index)
- [Hugging Face QLoRA/quantization](https://huggingface.co/docs/peft/main/developer_guides/quantization)
