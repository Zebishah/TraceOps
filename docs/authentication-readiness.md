# Authentication and Resend email verification

OpsPilot now supports mailbox verification with Resend. Password hashing, login rate limits, workspace roles, human approval checks, and scoped MCP OAuth remain in place. Verification is an explicit rollout setting; the default is off so deploying the schema and UI does not immediately block existing accounts.

## Backend environment

Set these on the **Python backend in Render**, or in `backend/.env` for local development. Resend keys never belong in browser code, a `NEXT_PUBLIC_` variable, or Git.

| Variable | Value |
| --- | --- |
| `EMAIL_VERIFICATION_ENABLED` | `true` after the migration, sender, and frontend are ready; default `false` |
| `RESEND_API_KEY` | A Resend sending-access key restricted to `nagumo-spot.isroot.in` |
| `EMAIL_FROM` | `OpsPilot <opspilot@nagumo-spot.isroot.in>` |
| `FRONTEND_BASE_URL` | The frontend's actual public HTTPS origin, such as your Vercel production URL; no `/app`, query string, credentials, or fragment |

Optional settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `EMAIL_VERIFICATION_EXPIRE_MINUTES` | `60` | Link lifetime; allowed range 5–1440 minutes |
| `EMAIL_VERIFICATION_DAILY_LIMIT` | `80` | Maximum application verification-send attempts per rolling 24-hour Redis window; leaves some of a 100/day free allowance for other uses |
| `EMAIL_DELIVERY_TIMEOUT_SECONDS` | `10` | Resend request timeout |

All projects in the same Resend account share the provider's sending allowance. Raising OpsPilot's limit does not raise the provider's quota. The application budget is not a delivery or billing guarantee.

No new frontend environment variable is required. Keep its existing `OPSPILOT_BACKEND_URL` pointing to the public backend. Locally, use `http://localhost:5173` for `FRONTEND_BASE_URL` if that is your frontend port. Production requires HTTPS.

The backend validates delivery configuration at startup when verification is enabled. Missing keys, malformed sender addresses, and unsafe frontend URLs fail startup rather than silently bypassing verification. The existing `MCP_AUTHORIZATION_SERVER_URL` and `MCP_RESOURCE_URL` still point to the public backend; email setup does not change the MCP issuer.

## Deploy in this order

1. Review and merge the auth PR. Keep `EMAIL_VERIFICATION_ENABLED=false` while rolling out.
2. From `ops-pilot/backend`, with the intended database configured, run:

   ```bash
   uv run alembic upgrade head
   ```

   The new revision is `8d29e0000001`. It adds `users.email_verified_at` and `email_verification_tokens`; it does not mark any old address as verified. Run migrations once against the intended database through your normal trusted release process.
3. Deploy the backend and frontend. The frontend must serve `/verify-email` before email links use it.
4. Confirm the sender domain is verified in Resend. Create a sending-only API key, add the backend environment values, and turn **off click and open tracking for this sender domain** in Resend's domain configuration. Auth links should not be rewritten for tracking.
5. Set `EMAIL_VERIFICATION_ENABLED=true` and restart/redeploy the backend. Test signup, inbox delivery, link confirmation, login, and a fresh MCP connection using a mailbox you control. Automated tests use synthetic delivery and do not establish real inbox delivery.

## Existing accounts

Existing users remain unverified after migration. Once the setting is on, they must visit `/verify-email`, request a link using their current account email, confirm it, and sign in again. Existing REST sessions and MCP access/refresh paths are also gated; an older token does not bypass verification.

Check existing account email addresses before enabling. Demo addresses such as `zohaib@example.com` cannot receive your mail. A trusted operator must correct those account addresses to mailboxes their owners control before rollout. Do not set `email_verified_at` merely to bypass the check, and do not change an account to an address the owner has not authorized.

Turning the setting off restores the previous access policy and can allow previously issued tokens to work again if otherwise valid. It is a rollback of enforcement, not proof of mailbox ownership or token revocation. Keep enforcement on after a successful rollout.

## User flow

- Signup creates the account, organization, and owner membership. With verification enabled, the response includes `verification_required=true`; the browser does not attempt login or receive a session token yet.
- The confirmation email uses the app's ivory, forest, and gold theme and has HTML and plain-text versions. The frontend handles provider failure explicitly after signup and lets the user request another link without recreating the account.
- Correct login credentials for an unverified account return `403` with `detail.code=email_verification_required`. Wrong credentials retain the generic invalid-email-or-password error.
- Opening a link renders a confirmation screen. Only pressing **Verify my email** sends the confirmation POST. Success does not sign the user in automatically.
- Existing MCP sign-in forms preserve their OAuth context and show an email-verification link. After confirming the email, return to that form and sign in again. Expired forms must restart from the AI application.

## API

| Endpoint | Method | Behavior |
| --- | --- | --- |
| `/api/v1/auth/register` | POST | Existing request; adds `email_verified`, `verification_required`, and `verification_email_sent` response fields |
| `/api/v1/auth/verification/request` | POST | Body `{ "email": "person@example.com" }`; generic response for unknown, verified, disabled, and send-failed accounts |
| `/api/v1/auth/verification/confirm` | POST | Body `{ "token": "the-token-from-the-link" }`; confirms a valid, unexpired token once |

Verification requests are limited to 10 per connection peer per hour and 3 per normalized email per hour. Confirmation attempts are limited to 20 per peer per minute. Redis failure blocks these operations. These use the existing trusted connection-peer policy rather than accepting arbitrary forwarded IP headers. Requests through a shared frontend proxy can therefore share a peer bucket; tune the deployment/trusted-proxy design if traffic grows.

## Token and delivery safety

Tokens use 32 cryptographically random bytes. Only SHA-256 hashes are stored; verification tokens are separate from access tokens and OAuth codes. Each token is bound to both the user and the email address it was issued to. A successful claim locks the user row before claiming a token with conditional SQL, records verification, and invalidates other outstanding links in the same transaction. Expired, consumed, unknown, changed-email, inactive-account, and repeated claims fail.

Failed resends invalidate only their own token, preserving earlier valid links. Resend receives a unique idempotency key per delivery. Provider errors, API keys, raw tokens, full verification URLs, and recipients are not included in application delivery logs. A provider acknowledgement means the send was accepted, not that inbox delivery is guaranteed.

Links use `/verify-email#token=...`. The URL fragment is not sent in HTTP requests; the browser reads it into memory and removes it from the address bar. It is not kept in local/session storage. Confirmation is POST-only so ordinary mail link previews do not consume tokens. The page sets no-referrer metadata and does not request automatic verification on mount. The frontend proxy allows only the two explicit verification endpoints, validates their bodies, requires same-origin mutations, and does not forward verification query strings or old session credentials.

Expired/consumed token rows are cleaned up for that user when a new email is issued. No new scheduler, database keep-alive, or idle polling was introduced.

## Validation

Regression tests exercise actual verification SQL through SQLite, hash-only storage, expiry, replay, mailbox changes, failure recovery, delivery budgets, configuration checks, API responses, existing-token enforcement, MCP sign-in/token gates, and frontend proxy/token contracts. PostgreSQL migration SQL is generated and reviewed separately. Live mailbox delivery and ChatGPT/Claude callback behavior must be checked after deployment with real configuration.

Password reset, email changes through a user-facing settings flow, and MFA remain separate follow-ups. This feature is not a complete security audit.

References: [Resend sending API](https://resend.com/docs/api-reference/emails/send-email), [Resend API keys](https://resend.com/docs/dashboard/api-keys/introduction), and [OWASP email verification](https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html).
