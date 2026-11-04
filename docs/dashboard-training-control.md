# Dashboard training control

The **AI & Models → Training runs** tab controls durable LoRA / QLoRA jobs. The API stores the queue; a separate trusted Linux worker runs the existing prepare/train/evaluate/package tools. PyTorch never loads inside the FastAPI service. Training does not sign a production release or switch the incident classifier.

## Deploy the API

From **ops-pilot/backend**, after installing this revision:

```bash
uv sync --frozen --group dev
uv run alembic upgrade head
```

The new migration is `9e30f0000001`, after `8d29e0000001`. Deploy the backend with training disabled until the migration and worker settings are ready. Keep all existing backend settings.

| Backend environment variable | Value |
| --- | --- |
| `TRAINING_ENABLED` | `true` after the migration and worker credential are ready; defaults to `false` |
| `TRAINING_WORKER_TOKEN` | A new random secret of at least 32 characters, shared only with trusted training workers |
| `TRAINING_QLORA_ENABLED` | `false` for CPU-only operation; set `true` after configuring a working CUDA environment |
| `TRAINING_MAX_RUNTIME_SECONDS` | Optional; defaults to `5400`, allowed range `60`–`14400` |

Generate the worker secret locally once with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Put the same value in Render's backend settings and the private worker environment file. Do not put it in frontend variables, source control, browser storage, or a screenshot.

The API reuses the existing S3 settings: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME`. The bucket must be private. The backend principal needs PutObject, GetObject and DeleteObject on the `training/` prefix. No public ACL is set. Completed ZIP downloads use organization-authorized, 60-second signed URLs. There are no new frontend secrets or package dependencies.

## Connect a CPU worker

Use a separate machine with enough RAM and disk space for the model, checkpoints and adapter. Do not run PyTorch in a small Render web service or a Vercel function. From **ops-pilot/backend**:

```bash
uv sync --project finetuning --frozen
cp finetuning/control-worker.env.example finetuning/control-worker.env
```

Edit **backend/finetuning/control-worker.env** with your backend HTTPS URL ending in `/api/v1` and the same worker token. The worker opens outbound HTTPS requests; it does not need an inbound port.

Process one eligible queued job, then exit:

```bash
uv run --env-file finetuning/control-worker.env --project finetuning --frozen python -m finetuning.control_worker --device cpu
```

To stay connected and accept future jobs:

```bash
uv run --env-file finetuning/control-worker.env --project finetuning --frozen python -m finetuning.control_worker --device cpu --watch
```

`--watch` polls every 30 seconds while idle. It keeps the backend/database awake. Use the one-job command for occasional demos to reduce Neon usage. During a run, the worker reports every five seconds. The dashboard polls every eight seconds only while it has active jobs and is visible. Run summaries omit the stored dataset from SQL reads.

Use a service supervisor or container that kills the worker's entire process group when it stops (for systemd, `KillMode=control-group`). Graceful SIGTERM, user cancellation, runtime deadlines and connection failures terminate the subprocess group. SIGKILL or a machine failure cannot be handled by Python; process supervision is needed to prevent orphaned work. An expired lease is failed, never silently requeued. Retry explicitly creates a new run.

## CUDA / QLoRA

The frozen environment above contains CPU PyTorch. It does not enable CUDA. Follow the existing [GPU environment notes](finetuning-production-hardening.md) to create and validate a hardware-specific environment with CUDA PyTorch and bitsandbytes. In that environment run the same `finetuning.control_worker` module with `--device cuda`, and supply the two worker environment variables. Set `TRAINING_QLORA_ENABLED=true` on the API only after that environment works. CPU workers never claim QLoRA jobs. No CUDA execution is claimed by the CPU checks.

## Use the dashboard

1. Deploy the matching frontend and sign in as an owner or administrator.
2. Open **AI & Models → Training runs → New training run**.
3. Choose LoRA/QLoRA, adapter rank, epoch/step/token budgets and dataset source.
4. Upload or paste de-identified JSONL with `title`, `description`, `category`, `priority`, `group_id`. Related cases must share a group. The limit is 200,000 UTF-8 bytes, 1,000 accepted records and at least three independent groups. Review the labels and confirm the data use.
5. Queue the run, then start a worker if one is not watching. Queued does not mean training has started. The profile pins `Qwen/Qwen2.5-0.5B-Instruct` to a full Hub revision and never accepts arbitrary model URLs or shell commands from the browser.
6. Inspect actual optimizer steps, reported epoch, latest validation loss and held-out metrics. These counters show completed work against budgets; early stopping can complete below a budget.
7. Cancel queued work immediately, or request cancellation of running work. Running work is not labelled cancelled until the worker confirms it. Retry failed/cancelled work as a separate run.
8. Download a completed, verified adapter ZIP. It excludes datasets, optimizer state and checkpoints. The displayed checksum identifies the ZIP bytes, not a signed production release.

There is one active run per organization, a global admission cap of ten and one global worker execution slot. A database mutex serializes admission and claims across API instances. Idempotency IDs prevent duplicate submissions; every worker write is fenced by a fresh lease token. Leases expire after 90 seconds without a heartbeat. Queued jobs expire after 24 hours if no eligible worker claims them. Raw process logs stay private on the worker; the dashboard receives bounded error codes and aggregate metrics.

Datasets are retained privately in PostgreSQL to support retries. Worker datasets, logs, reports and checkpoints remain in the ignored `backend/finetuning/control-work/` directory; maintain an operator retention policy and remove old terminal-run data when no longer needed. The service does not export production incidents automatically or prove that supplied labels are correct/de-identified. Operator review remains required.

## Routes

All organization routes require existing session/JWT authentication and owner/admin membership:

| Method | Under `/api/v1/organizations/{organization_id}/training` | Purpose |
| --- | --- | --- |
| GET | `/capabilities` | Flags, immutable model profile and recently reported worker presence |
| GET / POST | `/runs` | Latest 50 summaries / queue a run |
| GET | `/runs/{id}` | Scoped progress and result |
| POST | `/runs/{id}/cancel` | Cancel or request cancellation |
| POST | `/runs/{id}/retry` | Retry as a new, idempotent run |
| GET | `/runs/{id}/download` | Obtain a short-lived private ZIP download |

Trusted worker routes under `/api/v1/internal/training` use the separate bearer credential. Claim takes a declared CPU/CUDA device. Heartbeat, finish and streamed artifact upload also require `X-Training-Lease`. They are deliberately excluded from the frontend proxy.

## Production release

A successful training job remains **unapproved**. Its test metrics do not replace a paired Groq baseline, reviewed production evidence or domain approval. Use the existing signed release workflow before changing `INCIDENT_CLASSIFIER_BACKEND`. This feature provides no automatic model promotion and changes no financial/approval rules.

## Verification

The test suite covers real SQL state transitions and tenant scoping, worker credentials and role checks, idempotency conflicts, CPU/QLoRA routing, cancellation, lease expiry, bounded bodies, uploads and download authorization. Worker tests execute real short-lived subprocesses to check orchestration, ZIP contents and deadline termination; they do not claim model-quality evidence. A dedicated PostgreSQL CI job applies the migration chain and tests simultaneous submissions and claims. The existing isolated LoRA CI smoke continues to exercise actual optimizer/save/reload mechanics.
