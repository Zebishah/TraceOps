# Temporary Modal QLoRA demo deployment

This runbook deploys the repository's existing authenticated FastAPI classifier worker to Modal with a T4 GPU. The worker loads the local QLoRA adapter and downloads its pinned Qwen base model from Hugging Face.

## Scope and release status

- Base model: `Qwen/Qwen2.5-0.5B-Instruct`, pinned by the adapter artifact manifest.
- Adapter: `finetuning/adapters/synthetic-v1-qlora` (NF4 QLoRA).
- Modal exposes the worker's existing `POST /classify` route.
- The worker runs in `development` mode and returns `X-Classifier-Release: development`.
- The current synthetic dataset is not eligible for the repository's signed production release process. Connect this only to a separate Render staging service. Leave the existing Groq production service unchanged.

## 1. Get the deployment branch and verify the local artifact

From the backend directory:

```bash
git fetch origin
git switch deploy/modal-qlora-demo
uv run --project finetuning --frozen python -c '
from pathlib import Path
from finetuning.artifacts import verify_artifact
path = Path("finetuning/adapters/synthetic-v1-qlora")
artifact = verify_artifact(path)
assert artifact.loading.quantization == "nf4"
print("Verified adapter:", artifact.fingerprint())
'
```

The adapter is intentionally not committed to Git. Keep the verified adapter folder in your local checkout; Modal uploads it as part of deployment. If the verification command says a file is missing, restore the adapter from the downloaded Kaggle archive first.

## 2. Configure Modal CLI and a private worker secret

Install the Modal CLI in an isolated tool environment and authenticate:

```bash
uv tool install modal
modal setup
```

Generate a long random token locally:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

In the Modal dashboard, open **Secrets** and create a secret named `opspilot-classifier-demo` with:

| Key | Value |
| --- | --- |
| `CLASSIFIER_ADAPTER_PATH` | `/root/backend/finetuning/adapters/synthetic-v1-qlora` |
| `CLASSIFIER_SERVING_TOKEN` | The random token you generated |
| `CLASSIFIER_ENVIRONMENT` | `development` |
| `CLASSIFIER_DEVICE` | `cuda` |
| `CLASSIFIER_QLORA` | `true` |
| `CLASSIFIER_GENERATION_TIMEOUT_SECONDS` | `30` |
| `CLASSIFIER_STARTUP_TIMEOUT_SECONDS` | `600` |
| `CLASSIFIER_CPU_THREADS` | `2` |

Do not put the token in this file, in Git, or in the Modal app source. Do not add a release manifest or release public key for this synthetic-data demo.

## 3. Deploy the app

Run from the backend directory, where `finetuning/modal_app.py` and the adapter folder exist:

```bash
modal deploy finetuning/modal_app.py
```

Modal prints the deployed HTTPS app URL. Use that URL as `WORKER_ROOT` below. Append `/classify` for classification requests. Modal downloads the pinned Qwen base model when its GPU worker starts; the local adapter is copied into the worker package.

## 4. Test Modal directly

Open a Bash shell (type `bash` if your terminal is Fish), then set the worker URL and enter the token without displaying it:

```bash
WORKER_ROOT='https://YOUR-MODAL-APP-URL'
read -rsp 'Worker token: ' WORKER_TOKEN; echo
export WORKER_TOKEN
```

Paste the same token you saved in the Modal Secret and press Enter. Then test:

```bash
curl -i "$WORKER_ROOT/health/ready"
curl -i "WORKER_ROOT/classify" \
  -H "Authorization: Bearer $WORKER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test payment delay","description":"A demo payment is delayed; no payment has been lost."}'
```

Replace `WORKER_ROOT` with the actual URL, for example `https://your-app--classifier-api.modal.run`. A successful classify response is JSON with `category` and `priority`, and a response header `X-Classifier-Release: development`. First startup can take longer while the model downloads and loads. If needed, inspect the Modal app logs in the dashboard or run `modal app logs opspilot-qwen-qlora-demo`.

## 5. Connect a separate Render staging service

On a separate staging Render service, set:

```dotenv
ENVIRONMENT=staging
INCIDENT_CLASSIFIER_BACKEND=finetuned
FINETUNED_CLASSIFIER_URL=https://YOUR-MODAL-APP-URL/classify
FINETUNED_CLASSIFIER_TOKEN=the-same-worker-token
FINETUNED_CLASSIFIER_TIMEOUT_SECONDS=60
FINETUNED_CLASSIFIER_FALLBACK_ENABLED=false
```

Remove or leave unset `FINETUNED_CLASSIFIER_RELEASE_ID` on staging. Do not set `INCIDENT_CLASSIFIER_BACKEND=finetuned` on the existing production Render service. Setting fallback to false on staging makes worker failures visible rather than silently returning a Groq result. Warm Modal with a direct request before the first Render test.

Use a harmless demo incident. Check Modal logs and Render logs to confirm the request used the adapter worker. Then restore the staging classifier to Groq or delete the temporary staging service if you are done.

## 6. Stop Modal after the test

```bash
modal app stop opspilot-qwen-qlora-demo
```

Stopping the Modal app terminates its running containers. The deployment can be created again later with `modal deploy finetuning/modal_app.py`.

## Cost note

Modal's dashboard currently showed only $1 of monthly compute credit available. A payment method is required to use Modal. Before adding one, check **Settings → Usage & Billing** and set the smallest workspace usage budget you can, plus a $0 spend limit if the dashboard permits it. A T4 is currently listed at $0.000164/second, with CPU and memory billed separately; do not assume the $1 credit covers a full day. The function is capped at one container and scales down after 15 idle seconds, but cold starts may recur.
