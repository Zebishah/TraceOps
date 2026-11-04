# OpsPilot frontend

React 19, strict TypeScript, and Next.js 16. Production runs as a Node web application on Vercel or Render. The existing Sites/Vinext preview and Worker build remain supported.

## Local development

Use Node 22.13 or newer and the pinned pnpm version in `package.json`.

```sh
corepack enable
pnpm install --frozen-lockfile
cp .env.example .env.local
pnpm dev:node
```

Run these commands from `frontend/`. Set `OPSPILOT_BACKEND_URL` in `.env.local` to the backend root, for example `https://ops-pilot-bjmb.onrender.com`. Do not use the frontend URL, `/docs`, or an API key. Restart after changing it. The allowlisted API proxy, documentation link, and MCP fallback all use this one server setting. Do not prefix it with `NEXT_PUBLIC_` or `VITE_`.

## Deploy on Vercel

1. Import this repository and select **frontend** as Root Directory.
2. Select Next.js and Node 22.x. `vercel.json` supplies the install and build commands.
3. Add `OPSPILOT_BACKEND_URL` in the project's environment variables for Production and Preview, then deploy.
4. Use Fluid compute / a function duration that permits the proxy's exported 120-second maximum. Background investigation is asynchronous; the browser polls the saved job.

Vercel functions have a 4.5 MB request/response payload limit. Document and audio file inputs therefore enforce a **4 MiB** frontend cap on Vercel, leaving space for multipart metadata. Choose Render if you need the backend's full **10 MiB** upload allowance. Speech responses are limited to 4 MiB. Files rejected by the host cannot reach the proxy.

## Deploy on Render

Create a **Node Web Service**, not a static site. Use the repository-root `render.frontend.yaml` blueprint or these settings:

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Build command | `corepack enable && pnpm install --frozen-lockfile && pnpm run build:node` |
| Start command | `pnpm start` |
| Health check | `/login` |
| Node | `22` (also pinned in `.node-version`) |
| Environment | `OPSPILOT_BACKEND_URL` = your HTTPS backend root |

The start script binds to `0.0.0.0` and Render's `PORT`. Production cookies are Secure and HttpOnly. Requests go through the same-origin server proxy, so this frontend does not need direct browser CORS access to the backend.

## Before switching production traffic

Deploy the companion backend changes first, retaining its database, Redis, Inngest, AI provider, and authorization settings. No database migration is introduced here. Backend uptime and workers must be healthy independently of the frontend. Check `/api/backend/health` on the frontend and sign in to an existing account. Confirm an incident can be created, investigated, and read back. Use controlled test records for approval checks.

Voice is optional. To enable it on the **backend**, configure `GROQ_API_KEY`, `VOICE_ENABLED=true`, and optionally `VOICE_TTS_ENABLED=true`. Voice requests use Redis-backed limits and require owner/admin/operator access. No provider keys belong in the frontend. The UI records or uploads audio, lets the user edit and confirm the transcript, and then adds it to a draft. Creating the incident remains a separate action. Spoken briefs require an explicit English excerpt of at most 200 characters; long findings are never silently truncated. Audio is not saved in browser storage.

The System page reports the configured classifier mode, fallback setting, and release digest. Fine-tuning is an offline backend process, not a browser action. See [the release runbook](../docs/finetuning-production-hardening.md). Configured settings do not prove model quality or identify the model used for an older result.

## Feature audit

| Backend capability | Frontend surface |
| --- | --- |
| Incident creation, background investigation, classify, retrieve evidence, retry, saved results | Incidents and investigation workspace; separate advanced controls |
| Evidence, operational tools, similar incident memories, clarification | Investigation tabs; clarification creates a follow-up draft |
| Acknowledge and resolve without action | Incident controls with role checks |
| Human decision, exact proposed payload, execution and recovery state | Approvals; explicit confirmation and separate recovery status |
| Document upload, process, reindex, chunk previews | Knowledge documents and document detail |
| Semantic retrieval, cited answers, curated project search | Knowledge Search, Ask Knowledge, Developer Hub |
| Voice transcription and short speech generation | New incident voice intake; saved decision brief |
| Customers, orders, payments, memories, jobs, delivery and recovery reads | Operations, Memory, Jobs, Automations |
| Workspace configuration, readiness and published evaluations | System & Integrations, Quality & Evaluations |
| MCP endpoint, scoped personal token, tool catalog | MCP Connections |

Search fields update after a 350 ms pause (500 ms for semantic retrieval). Enter/Search still works immediately. Clearing resets results, changed filters reset pagination, and cancelled requests cannot overwrite newer searches. Evaluation case search filters locally while typing. Ask Knowledge is a generation action and remains an explicit submission.

Member administration, token revocation, persisted MCP client activity, and training actions have no corresponding dashboard backend API. Their absence is shown honestly; the UI does not invent controls or data. Refund execution is an internal-ledger simulation, not proof of external provider money movement. The public landing walkthrough is illustrative.

## Validate

```sh
pnpm typecheck
pnpm test
pnpm build:node
pnpm test:production
```

The production smoke test starts a temporary Next server and a synthetic upstream. It checks auth cookies, API forwarding, voice multipart/WAV, host/origin restrictions, and basic page serving without calling real providers or creating production records. It requires a completed Node build. It does not certify a deployed backend or external integrations.

The managed preview uses `pnpm dev`; the Sites build uses `pnpm build`. Preserve `.openai/hosting.json`, `worker/index.ts`, the Vite integration, and the maintained build scripts. Generated `.next`, `dist`, and local runtime state must remain untracked.
