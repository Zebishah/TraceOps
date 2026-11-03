# OpsPilot frontend

A React 19 / TypeScript workspace and product landing page, built with Vinext and deployed as a Cloudflare Worker through Sites.

## Run locally

Use Node.js >=22.13 and the pinned pnpm version in package.json.

```sh
pnpm install --frozen-lockfile
pnpm dev
```

## Validate

```sh
pnpm exec tsc --noEmit
node --experimental-strip-types --test tests/proxy-policy.test.ts
pnpm build
```

## Backend connection

The server-side allowlisted proxy connects to https://ops-pilot-bjmb.onrender.com. Sign in using an existing OpsPilot backend account. Access tokens stay in an HttpOnly, SameSite cookie; backend authorization remains authoritative. Credentials and records are never seeded into the frontend.

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
