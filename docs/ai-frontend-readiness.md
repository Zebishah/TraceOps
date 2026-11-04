# Voice and fine-tuned classification: frontend handoff

This branch adds no recorder UI and does not deploy or activate a model. It supplies the missing proxy connection, typed voice response contracts, capability discovery, and repeatable live smoke checks. Training code is implemented; production model approval is still a separate evidence requirement.

## 1. Enable voice on the backend

Keep the rest of your existing backend environment. Set these on the backend host:

```dotenv
VOICE_ENABLED=true
VOICE_TTS_ENABLED=false
VOICE_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
VOICE_TIMEOUT_SECONDS=30
VOICE_REQUESTS_PER_MINUTE=10
INCIDENT_CLASSIFIER_BACKEND=groq
```

The backend also needs its existing valid `GROQ_API_KEY` and reachable `REDIS_URL`. These values never belong in frontend/public environment variables. Restart or redeploy after updating configuration. Enabling voice now rejects an empty provider key at startup, but a nonempty key still needs live provider verification. The hosted transcription request consumes provider quota.

The frontend keeps its existing server-side `OPSPILOT_BACKEND_URL`, pointing to the backend origin without `/api/v1`. No new public frontend secret is needed. Deploy the backend and proxy changes before enabling the recorder UI.

## 2. Connect the recorder

Use HTTPS in deployment (localhost is permitted for browser development). Request microphone access only after a user action. Choose a supported MediaRecorder format at runtime; browsers differ. The backend recognizes WAV, WebM, Ogg, FLAC, MP3 and M4A containers. Stop microphone tracks on stop, cancel, navigation and unmount; revoke audio preview object URLs.

First call the same-origin proxy:

```http
GET /api/backend/organizations/{organization_id}/voice/capabilities
```

The response includes `enabled`, `speech_enabled`, `transcription_model`, `max_audio_bytes`, `requests_per_minute`, `supported_containers`, `max_speech_characters`, and `requires_confirmation=true`. This is configuration discovery, not proof that Groq/Redis are currently healthy. It requires a signed-in user with incident-creation permission in the organization. Hide or disable recording when `enabled=false`.

After recording, upload with the existing API helper and new schema:

```ts
import { api } from '@/lib/product/client';
import { voiceTranscriptionSchema } from '@/lib/product/voice-contracts';

export async function transcribeRecording(
  organizationId: string,
  recording: Blob,
  signal?: AbortSignal,
) {
  const form = new FormData();
  form.append('file', recording, 'recording');
  return api(
    `organizations/${organizationId}/voice/transcriptions`,
    voiceTranscriptionSchema,
    { method: 'POST', body: form, signal },
  );
}
```

Do not manually set multipart Content-Type; the browser adds the boundary. The existing API helper already handles FormData correctly. The frontend session cookie is handled by the proxy; do not put a backend bearer token in browser storage.

The backend endpoint is `POST /api/v1/organizations/{organization_id}/voice/transcriptions`. Multipart fields are `file` and optional `language` (two lowercase letters, such as `en` or `ur`; omit for provider detection). The audio file must be nonempty and no larger than 10 MiB. Browser recording should have its own duration/size cutoff.

Expected JSON:

```json
{"text":"The customer reports two charges.","model":"whisper-large-v3-turbo","requires_confirmation":true}
```

Place the returned text into an editable description or review panel. Preserve any existing typed content and let the user choose whether to append or replace it. Recording/transcribing must not submit the incident, start an investigation, or approve an action. The user reviews and clicks Create incident separately.

Handle 401/403 for access, 413 for size, 415 for unsupported audio, 422 for rejected input, 429 for rate limits (respect Retry-After), and 502/503/504 for temporary service/proxy failures. Do not repeatedly retry an upload automatically. Cancelling the frontend request stops waiting; it does not promise cancellation of work already sent to the hosted provider. Backend provider work has its own deadline.

The optional speech endpoint uses POST `.../voice/speech` with JSON `{"text":"Short text"}`, a 200-character limit and WAV output. It needs both VOICE_ENABLED and VOICE_TTS_ENABLED. The proxy now forwards bounded, validated WAV responses only on that exact path. Read them as a Blob with fetch, not the JSON-only api helper.

## 3. Fine-tuning uses the existing incident APIs

No training runs in the browser or automatically at API startup. Continue using the existing classify/background-investigation UI and endpoints. The backend selects the provider:

```http
POST /api/backend/organizations/{organization_id}/incidents/{incident_id}/classify
```

Classification returns category, priority, and confidence (number or null). Null means unavailable; use the existing Unavailable display. Never expose the worker URL, serving token, release signing key, or worker settings in frontend code.

Production activation requires real reviewed/de-identified incidents, proper training, paired held-out evaluation against Groq, and an approved signed release. The committed synthetic smoke adapter is not approved. Its poor results cannot be fixed by adding an environment variable. See [the training and release runbook](finetuning-production-hardening.md).

Deploy the approved package on a separate private model worker with sufficient measured memory and a pre-cached pinned base model. From `ops-pilot/backend`:

```bash
uv sync --project finetuning --frozen
uv run --project finetuning --frozen uvicorn finetuning.serve_classifier:app --env-file finetuning/worker.env --host 127.0.0.1 --port 8001 --workers 1
```

Use `backend/finetuning/worker.env.example` as the template. Required worker variables:

| Worker variable | Meaning |
| --- | --- |
| CLASSIFIER_ENVIRONMENT | production |
| CLASSIFIER_ADAPTER_PATH | Absolute verified adapter-package path |
| CLASSIFIER_SERVING_TOKEN | Separate random secret, 32–256 characters |
| CLASSIFIER_RELEASE_MANIFEST | Signed release JSON path |
| CLASSIFIER_RELEASE_PUBLIC_KEY | Trusted base64 public verification key |
| CLASSIFIER_DEVICE | cpu, or supported cuda in a separately verified GPU environment |
| CLASSIFIER_GENERATION_TIMEOUT_SECONDS | 8 by default |
| CLASSIFIER_STARTUP_TIMEOUT_SECONDS | 120 by default |
| CLASSIFIER_CPU_THREADS | 2 by default |

Use the platform's private networking/HTTPS for separate machines. Loopback binds only on the worker machine; remote access needs suitable private binding, routing and TLS. The CPU lock does not enable CUDA. QLoRA still needs verification on target GPU hardware.

Only after readiness and quality approval, configure the main backend:

```dotenv
INCIDENT_CLASSIFIER_BACKEND=finetuned
FINETUNED_CLASSIFIER_URL=https://YOUR_PRIVATE_WORKER/classify
FINETUNED_CLASSIFIER_TOKEN=THE_SAME_WORKER_SECRET
FINETUNED_CLASSIFIER_RELEASE_ID=THE_ID_FROM_RELEASE_APPROVAL
FINETUNED_CLASSIFIER_TIMEOUT_SECONDS=10
FINETUNED_CLASSIFIER_FALLBACK_ENABLED=true
```

These capitalized descriptive values are documentation placeholders: use your real deployment values. Never invent a release ID or sign unreviewed demo data. Restart the API. Roll back by selecting groq and restarting. No production setting was changed by this PR.

## 4. Run the live checks

From `ops-pilot/backend`, run `uv sync --frozen --group dev`. In a temporary terminal session set `OPSPILOT_SMOKE_TOKEN` to a signed-in user's backend access token. Do not commit it or put it in screenshots, shell-history commands or frontend code. This is separate from the private worker token.

```bash
uv run python -m scripts.check_ai_readiness --api-url https://YOUR_BACKEND --organization-id YOUR_ORGANIZATION_UUID --audio /absolute/path/to/short-recording.webm
```

This calls the deployed capability route, uploads the actual recording and verifies the transcript contract. It consumes a voice request and provider quota, but creates no incident and does not print/store the transcript. Check the actual transcription accuracy separately using a reviewed example. Omit --audio to check configuration/access only; that intentionally skips the provider transcription.

Once an approved worker is deployed, set FINETUNED_CLASSIFIER_TOKEN and FINETUNED_CLASSIFIER_RELEASE_ID in that terminal:

```bash
uv run python -m scripts.check_ai_readiness --worker-url https://YOUR_PRIVATE_WORKER/classify
```

It checks readiness/release identity and sends one harmless classification request. It fails on a release mismatch and never approves a model. Run it from a machine allowed to reach the private worker. One valid response is not a quality benchmark.

## 5. Automated verification

- Full backend: 933 passed, 16 skipped locally. Skips retain external-infrastructure/optional-ML requirements.
- Isolated frozen CPU ML tests: 31 passed, including actual tiny-model training/resume, process deadlines/recovery and a signed-worker-to-backend HTTP contract.
- Frontend: 13 contract/proxy tests passed, plus strict TypeScript checks for the changed pure modules and tests.
- Ruff and mypy passed, including the live-check script.
- Signed integration fixtures and provider responses in automated tests are artificial. They are not real model approval or a live Groq test.

Actual deployed voice requests, deployment environment updates, real model quality approval and target hardware checks require credentials/data/services unavailable in this coding session. The earlier pinned-Qwen synthetic mechanics run remains documented in finetuning-verification.json. No new real-data training or CUDA run is claimed.
