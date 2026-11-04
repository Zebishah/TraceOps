import test from 'node:test';
import assert from 'node:assert/strict';
import { anonymousAuthPath, authInputSchema, registrationResponseSchema, verificationTokenFromFragment } from '../lib/product/auth-contracts.ts';
import { allowedBackendPath } from '../lib/product/proxy-policy.ts';
import { ApiError, post } from '../lib/product/client.ts';
import { z } from 'zod';

test('verification has only two public proxy operations with strict bodies', () => {
  for (const path of ['auth/verification/request', 'auth/verification/confirm']) {
    assert.equal(allowedBackendPath(path), true);
    assert.equal(anonymousAuthPath(path), true);
  }
  for (const path of ['auth/verification/admin', 'auth/verification/confirm/extra', 'auth/verification/%2fconfirm']) assert.equal(allowedBackendPath(path), false);
  assert.equal(anonymousAuthPath('auth/mcp-token'), false);
  assert.equal(authInputSchema('auth/verification/request')?.safeParse({ email: 'not-email' }).success, false);
  assert.equal(authInputSchema('auth/verification/confirm')?.safeParse({ token: 'short' }).success, false);
});

test('only one valid fragment token is accepted; query strings and duplicate values are rejected', () => {
  const token = 'a'.repeat(43);
  assert.equal(verificationTokenFromFragment('#token=' + token), token);
  for (const value of ['', '?token=' + token, '#token=short', '#token=' + token + '&token=' + token, '#token=' + 'é'.repeat(43)]) assert.equal(verificationTokenFromFragment(value), null);
});

test('old backend registration stays compatible while verification-enabled signup is explicit', () => {
  assert.equal(registrationResponseSchema.parse({ id: 'id' }).verification_required, false);
  const result = registrationResponseSchema.parse({ id: 'id', verification_required: true, verification_email_sent: false });
  assert.equal(result.verification_required, true);
  assert.equal(result.verification_email_sent, false);
});

test('structured verification errors and Retry-After reach the auth UI', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: { code: 'email_verification_required', message: 'Verify your email', email: 'person@example.com' } }), { status: 403, headers: { 'retry-after': '42' } });
  try {
    await assert.rejects(post('auth/login', z.object({ authenticated: z.boolean() }), {}), (error: unknown) => error instanceof ApiError && error.code === 'email_verification_required' && error.message === 'Verify your email' && error.retryAfter === 42);
  } finally { globalThis.fetch = original; }
});
