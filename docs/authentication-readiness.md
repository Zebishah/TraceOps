# Authentication readiness

## Decision

Add email ownership verification before offering unrestricted public registration. The current email format check does not prove that a person controls the mailbox. Keep this separate from the MCP sign-in design change: there is no email delivery integration, verification-token storage, verified-email field, or account-recovery flow in the current backend.

Do not mark existing users verified automatically or enable a mandatory verification gate before working delivery and a migration plan exist. Existing users need a clear verification path; new public accounts should verify before gaining workspace access.

Email verification proves mailbox access. It does not replace workspace roles, MCP scopes, approval checks, or a second factor for high-risk accounts.

## Existing controls reviewed

| Area | Current behavior |
| --- | --- |
| Password storage | `pwdlib` recommended Argon2 hashing; passwords are not stored in plain text. |
| Sign-in attempts | Redis-backed limits by connection peer and normalized email; service failure blocks sign-in rather than bypassing the limit. |
| Credential errors | Invalid email/password responses do not identify which credential failed. |
| MCP authorization | Registered callback validation, PKCE, scoped tokens, resource/issuer checks, refresh-token rotation and revocation are separate from ordinary app access tokens. |
| Tenant access | Backend user membership and role checks remain authoritative. |
| Email ownership | Not verified. Registration creates an active account immediately. |
| Account recovery | No email-based password reset implementation. |

This is a focused source review, not a complete security audit or a claim that every deployment setting is safe.

## MCP sign-in change

`GET /oauth/login` and `POST /oauth/login` remain backend endpoints. The screen now uses the app's ivory, forest, and gold palette, a lightweight CSS connection illustration, responsive layouts, visible requested permissions, connection details, password visibility, and consistent error states. Application names are self-reported by OAuth clients; the UI also shows the callback origin so the name alone is not presented as proof of identity.

The browser form includes a signed proof bound to the client, callback, state, scope, PKCE challenge, resource, and explicit-redirect flag. It expires after ten minutes and requires the matching HttpOnly browser cookie. Production/HTTPS cookies use the `__Host-` prefix, Secure, SameSite=Lax, and Path=/. Multiple tabs can keep separate connection contexts in the same browser.

Changed or duplicate authorization fields, invalid context, foreign Origin headers, missing cookies, and expired or invalid proofs are rejected before password authentication. The registered client and requested scopes are checked again at submission. Existing rate limits remain in place. A failed login keeps the email and valid connection context, but never returns the submitted password.

Cancel returns `access_denied` and the original state only to the validated, registered callback; it issues no authorization code. Successful connections preserve the existing code exchange, PKCE, scopes, and resource.

The pages use no external fonts, analytics, or image requests. HTML values are escaped. Responses disable caching and referrer transmission, block framing, and use nonce-based Content Security Policy for local styles/scripts. The registered callback origin is included in `form-action` because browsers may also enforce that directive on the post-sign-in redirect.

A form proof protects browser consent integrity; it is not an access token, a password reset token, or a replacement for authorization-code replay protection.

## Deployment

Deploy the backend commit containing `oauth_login.py`, `oauth_form.py`, `oauth_login_ui.py`, and `oauth_login.css`. The CSS file is included in the Python wheel. No frontend build, database migration, or new environment variable is needed for this change.

Keep `MCP_AUTHORIZATION_SERVER_URL` and `MCP_RESOURCE_URL` aligned with the public HTTPS backend URL already configured for MCP. Do not move the authorization issuer to the Vercel frontend just to change its appearance. The public issuer origin is also used to check browser POST Origin headers behind a reverse proxy.

Already-open sign-in forms from before deployment need a fresh connection because they do not contain the new browser proof. Existing accounts and issued MCP tokens keep their current lifecycle. After deployment, check a fresh ChatGPT/Claude connection against the actual registered callback; local tests use synthetic clients and do not grant access to a real AI application.

## Next auth implementation

1. Choose a transactional email provider and verify a sender domain. Keep delivery credentials server-side.
2. Add `email_verified_at` and hashed, cryptographically random, single-use verification tokens with expiration. Consume tokens atomically. Never log raw tokens or complete verification URLs.
3. Add verification/resend endpoints, rate limits, generic responses, delivery failure handling, and a pending-verification screen. Build links from a configured trusted origin, not a user-supplied Host header.
4. Give existing accounts a deliberate verification rollout. Only enforce the gate across REST sign-in, existing sessions, and new MCP grants when the migration and delivery path are ready. Decide explicitly how already-issued sessions and MCP tokens are handled.
5. Add password recovery with a separate token purpose, single-use expiry, and session/token invalidation after reset. For owner/admin accounts, consider MFA and reauthentication for sensitive changes.

Reference: [OWASP Email Validation and Verification](https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html) and [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).
