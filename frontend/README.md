# OpsPilot frontend

A React 19 / TypeScript workspace and product landing page, built with Vinext and deployed as a Cloudflare Worker through Sites.

## Run locally

Use Node.js >=22.13 and the pinned pnpm version in package.json.

```sh
pnpm install --frozen-lockfile
cp .env.example .env.local
pnpm dev
```

## Validate

```sh
pnpm exec tsc --noEmit
node --experimental-strip-types --test tests/*.test.ts
pnpm build
```

## Backend connection

Set `OPSPILOT_BACKEND_URL` in `frontend/.env.local` to your backend root URL. `.env.example` contains the current Render example. Restart `pnpm dev` after changing it. The server-side allowlisted proxy, API documentation link, and MCP fallback all derive their origin from this setting. It is a server setting, not a `VITE_*` or `NEXT_PUBLIC_*` client variable. Sign in using an existing OpsPilot backend account. Access tokens stay in an HttpOnly, SameSite cookie; backend authorization remains authoritative. Credentials and records are never seeded into the frontend.

The dashboard collection, overview, safe configuration, curated project knowledge, and evaluation APIs require the companion changes in backend/ at the repository root. Run the backend checks and deploy before using the connected collections. No database migration is required.

## Product surfaces

- Incidents, background investigation, saved evidence, tool results, historical memories, acknowledgement, controlled retry, resolution without action, and customer-detail follow-up incidents.
- Human approval and rejection with explicit confirmation; scoped execution recovery status.
- Document upload, processing, reindexing, chunk previews, knowledge search, and cited answers.
- Tenant-scoped customer, order, payment, memory, automation delivery, job, and recovery browsing.
- MCP connection setup, scoped token generation, tool catalog, and explicit activity-availability messaging.
- Actual evaluation reports, dependency readiness, configured AI providers, architecture and account permissions.

The public landing walkthrough is illustrative. Its n8n screenshots show workflow designs, not live executions. Production workspace pages use API responses and show errors or empty states when unavailable. MCP activity persistence and member administration are not available in the current backend. Missing-customer clarification creates a follow-up incident; it does not silently rewrite an existing checkpoint.

## Verification limits

Frontend type checks, proxy policy tests, and the production build are local checks. Companion backend tests cover tenant isolation, validation, auth and safe fields. A live authenticated end-to-end run requires deploying that backend change and signing in; local checks do not certify production uptime, external payment execution or continuous laptop-hosted n8n availability.

## Hosting

Preserve .openai/hosting.json, worker/index.ts, the Sites Vite integration and the maintained scripts. Generated dist output and local runtime state are excluded from source control. The hosted preview remains owner-private. Run local frontend commands from frontend/.

## Dashboard troubleshooting

A successful sign-in only proves that the auth API is available. The dashboard also needs `/api/v1/organizations/{organization_id}/dashboard/...` from the backend changes in PR #2. If `/openapi.json` has no `/dashboard/` paths, that deployment is too old. Deploy the backend from this branch with the existing production environment, or run it locally and set `OPSPILOT_BACKEND_URL=http://127.0.0.1:8000`. No new migration is required for these dashboard read APIs.

Visit `/api/backend/health` on the frontend origin to check the configured proxy without signing in. A missing URL returns a configuration error; a missing backend route stays HTTP 404 instead of becoming a generic HTTP 502. Never paste passwords, cookies, or access tokens into issue reports.

For hosted Workers, set `OPSPILOT_BACKEND_URL` as the deployment's runtime variable. For local Vite development, `.env.local` is loaded into the local Worker binding. Dashboard navigation keeps the shared `/app` layout mounted; only the current content view displays loading or error states.

## Email verification

The `/verify-email` screen supports Resend verification links, resend requests, and explicit confirmation. Configure Resend on the **Python backend**, using `RESEND_API_KEY`, `EMAIL_FROM`, `FRONTEND_BASE_URL`, and `EMAIL_VERIFICATION_ENABLED`. No Resend key belongs in the frontend deployment. See [the authentication rollout guide](../docs/authentication-readiness.md) for the database migration, safe deployment order, optional limits, and existing-account behavior. The frontend keeps its existing `OPSPILOT_BACKEND_URL` setting.
