# Authentication and Resend email verification

IncidentIQ now supports automatic six-digit email verification with Resend. Password hashing, login rate limits, workspace roles, human approval checks, and scoped MCP OAuth remain in place. Verification is an explicit rollout setting; the default is off so deploying the schema and UI does not immediately block existing accounts.

## Backend environment

Set these on the **Python backend in Render**, or in `backend/.env` for local development. Resend keys never belong in browser code, a `NEXT_PUBLIC_` variable, or Git.

| Variable | Value |
| --- | --- |
| `EMAIL_VERIFICATION_ENABLED` | `true` after the migration, sender, and frontend are ready; default `false` |
| `RESEND_API_KEY` | A Resend sending-access key restricted to `nagumo-spot.isroot.in` |
| `EMAIL_FROM` | `IncidentIQ <opspilot@nagumo-spot.isroot.in>` |
| `FRONTEND_BASE_URL` | The frontend's actual public HTTPS origin, such as your Vercel production URL; no `/app`, query string, credentials, or fragment |

Optional settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `EMAIL_VERIFICATION_EXPIRE_MINUTES` | `60` | Legacy link lifetime; new verification codes expire after 10 minutes |
| `EMAIL_VERIFICATION_DAILY_LIMIT` | `80` | Maximum application verification-send attempts per rolling 24-hour Redis window; leaves some of a 100/day free allowance for other uses |
| `EMAIL_DELIVERY_TIMEOUT_SECONDS` | `10` | Resend request timeout |

All projects in the same Resend account share the provider's sending allowance. Raising IncidentIQ's limit does not raise the provider's quota. The application budget is not a delivery or billing guarantee.

No new frontend environment variable is required. Keep its existing `OPSPILOT_BACKEND_URL` pointing to the public backend. Locally, use `http://localhost:5173` for `FRONTEND_BASE_URL` if that is your frontend port. Production requires HTTPS.

The backend validates delivery configuration at startup when verification is enabled. Missing keys, malformed sender addresses, and unsafe frontend URLs fail startup rather than silently bypassing verification. The existing `MCP_AUTHORIZATION_SERVER_URL` and `MCP_RESOURCE_URL` still point to the public backend; email setup does not change the MCP issuer.

## Deploy in this order

1. Review and merge the auth PR. Keep `EMAIL_VERIFICATION_ENABLED=false` while rolling out.
2. From `ops-pilot/backend`, with the intended database configured, run:

   ```bash
   uv run alembic upgrade head
   ```

   The new revision is `8d29e0000001`. It adds `users.email_verified_at` and `email_verification_tokens`; it does not mark any old address as verified. Run migrations once against the intended database through your normal trusted release process.
3. Deploy the backend and frontend. Deploy both versions before enabling verification: the frontend code screen requires the backend `/verification/code` endpoint. OTPs reuse the existing verification table; no additional migration is needed beyond `8d29e0000001`.
4. Confirm the sender domain is verified in Resend. Create a sending-only API key, add the backend environment values, and turn **off click and open tracking for this sender domain** in Resend's domain configuration. Auth links should not be rewritten for tracking.
5. Set `EMAIL_VERIFICATION_ENABLED=true` and restart/redeploy the backend. Test signup, inbox delivery, code entry, automatic sign-in, and a fresh MCP connection using a mailbox you control. Automated tests use synthetic delivery and do not establish real inbox delivery.

## Existing accounts

Existing users remain unverified after migration. Once the setting is on, signing in with correct credentials automatically emails a code and opens the code-entry screen. Entering that code verifies the address and opens the workspace without a second sign-in. Existing REST sessions and MCP access/refresh paths are also gated; an older token does not bypass verification.

Check existing account email addresses before enabling. Demo addresses such as `zohaib@example.com` cannot receive your mail. A trusted operator must correct those account addresses to mailboxes their owners control before rollout. Do not set `email_verified_at` merely to bypass the check, and do not change an account to an address the owner has not authorized.

Turning the setting off restores the previous access policy and can allow previously issued tokens to work again if otherwise valid. It is a rollback of enforcement, not proof of mailbox ownership or token revocation. Keep enforcement on after a successful rollout.

## User flow

- Signup creates the account, organization, and owner membership and automatically sends a six-digit code. The response includes `verification_required=true` and the delivery result. No session is issued before verification.
- The browser opens the code-entry step with the signup email already selected. It supports pasting the code, mobile numeric keyboards, and one-time-code autofill. There is no initial send-email button in this flow.
- Successful code verification creates a session through the frontend proxy's HttpOnly cookie and navigates to `/app`. The access token is never returned to browser JavaScript.
- Correct sign-in credentials for an unverified account automatically send a code and return `403` with `detail.code=email_verification_required` and `verification_email_sent`. The browser shows the same code-entry screen. Incorrect credentials keep the generic invalid-email-or-password response and send no email.
- Reloading the code screen keeps only the email and resend timer in tab-scoped session storage; passwords and codes are never persisted. A gated existing workspace session carries its email into verification and automatically requests a code once. Opening `/verify-email` without any account context asks for the email first.
- Resend is available after 60 seconds and never disables code confirmation during that waiting period. Explicit initial delivery failures allow immediate retry. Incorrect, expired, and rate-limited submissions stay on the screen with a clear error.
- MCP sign-in automatically sends a code after valid credentials and shows code entry within the signed OAuth form. Verification continues the existing consent request to the validated client callback, preserving state, PKCE, scope, and resource. Resend and cancellation also preserve that context. Expired forms must restart from the AI application.
- Already-issued verification links remain supported through the legacy confirmation endpoint; they return to sign-in after confirmation. New deliveries contain a code instead of a link.

## API

| Endpoint | Method | Behavior |
| --- | --- | --- |
| `/api/v1/auth/register` | POST | Creates the workspace and automatically sends a verification code when enabled |
| `/api/v1/auth/login` | POST | Automatically sends a code for a valid, unverified account; never issues its session yet |
| `/api/v1/auth/verification/request` | POST | Body `{ "email": "person@example.com" }`; sends/resends a code; generic response for unknown, verified, inactive, and send-failed accounts |
| `/api/v1/auth/verification/code` | POST | Body `{ "email": "person@example.com", "code": "012345" }`; verifies a pending address once and returns a session token to the trusted proxy |
| `/api/v1/auth/verification/confirm` | POST | Legacy body `{ "token": "the-token-from-the-link" }`; confirms outstanding links without issuing a session |

Code requests are limited to 10 per connection peer per hour and 3 per normalized email per hour. Code submissions are limited to 20 per peer per minute and 5 per normalized email per 10 minutes, across peers and resends. Signup has its existing separate registration limit, and all delivery attempts share the application daily budget. Redis failure blocks these operations. These use the existing trusted connection-peer policy rather than accepting arbitrary forwarded IP headers. Requests through a shared frontend proxy can share a peer bucket.

## Code and delivery safety

Codes use cryptographically random six-digit values, including leading zeros, and expire in 10 minutes. Only HMAC-SHA-256 digests keyed by the backend secret are stored. Each digest includes the delivery UUID and address, preventing offline enumeration of the small code space from a database dump. Changing that secret invalidates pending codes.

A successful claim locks the user row, checks expiry and the current mailbox with conditional SQL, records verification, and invalidates all outstanding codes and legacy links in the same transaction. Expired, consumed, unknown, changed-email, inactive-account, and replayed proofs fail. Failed resends invalidate only their own delivery record, preserving earlier valid codes.

Resend receives a unique idempotency key per delivery. Provider errors, API keys, raw codes, legacy tokens, and recipients are not included in delivery logs. A provider acknowledgement means the send was accepted, not that inbox delivery is guaranteed. The message has HTML and plain-text versions in the app's ivory, forest, and gold theme.

The frontend proxy validates verification request bodies, requires same-origin mutations, strips query strings and old credentials from verification requests, and sets a bounded HttpOnly, SameSite=Strict session cookie after successful code verification. Production cookies are Secure. The response exposes only `verified` and `authenticated`, never the access token. Legacy fragment tokens stay in volatile memory and are removed from the address bar.

Expired/consumed records are cleaned up for the user when another email is issued. No scheduler or idle polling was added.

## Validation

Regression tests exercise actual verification SQL through SQLite, keyed code storage, expiry, replay, mailbox changes, failure recovery, delivery budgets, account attempt limits, configuration checks, automatic sends, session issuance, existing-token enforcement, MCP code-entry redirects, and frontend proxy contracts. Browser checks cover signup, reloads, code errors, immediate confirmation during resend cooldown, HttpOnly cookies, and mobile layouts. PostgreSQL migration SQL is generated and reviewed separately. Live mailbox delivery and ChatGPT/Claude callback behavior must be checked after deployment with real configuration.

Password reset, email changes through a user-facing settings flow, and MFA remain separate follow-ups. This feature is not a complete security audit.

References: [Resend sending API](https://resend.com/docs/api-reference/emails/send-email), [Resend API keys](https://resend.com/docs/dashboard/api-keys/introduction), and [OWASP email verification](https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html).
