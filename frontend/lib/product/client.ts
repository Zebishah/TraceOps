import { z } from 'zod';
import { verificationRequiredSchema } from './auth-contracts.ts';
import { rememberVerification } from './verification-flow.ts';

export class ApiError extends Error {
  verification: z.infer<typeof verificationRequiredSchema> | null = null;
  status: number; requestId: string | null; code: string | null; retryAfter: number | null;
  constructor(message: string, status: number, requestId: string | null = null, code: string | null = null, retryAfter: number | null = null) {
    super(message); this.name = 'ApiError'; this.status = status; this.requestId = requestId;
    this.code = code; this.retryAfter = retryAfter;
  }
}
export async function api<T>(path: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api/backend/${path}`, { ...init, headers, credentials: 'same-origin', cache: 'no-store' });
  let data: unknown;
  try { data = await response.json(); } catch { throw new ApiError('The server returned an unexpected response', response.status); }
  if (!response.ok) {
    let message = `Request failed (${response.status})`; let code: string | null = null;
    let verificationDetails: z.infer<typeof verificationRequiredSchema> | null = null;
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const verification = verificationRequiredSchema.safeParse(data.detail);
      if (verification.success) {
        message = verification.data.message; code = verification.data.code;
        verificationDetails = verification.data;
        // Recheck server routing after the proxy clears the unverified session cookie.
        if (typeof window !== 'undefined' && path !== 'auth/login' && window.location.pathname !== '/verify-email') {
          rememberVerification(verification.data.email);
          // eslint-disable-next-line @next/next/no-location-assign-relative-destination
          window.location.assign('/verify-email');
        }
      } else if (typeof data.detail === 'string') message = data.detail;
      else if (Array.isArray(data.detail)) message = 'Please check the submitted fields.';
    }
    const retry = response.headers.get('retry-after'); const seconds = retry === null ? NaN : Number(retry);
    const error = new ApiError(message, response.status, response.headers.get('x-request-id'), code, Number.isFinite(seconds) && seconds > 0 ? Math.min(86400, Math.ceil(seconds)) : null);
    error.verification = verificationDetails;
    throw error;
  }
  const parsed = schema.safeParse(data);
  if (!parsed.success) throw new ApiError('The backend response does not match this screen’s contract. Please refresh or check the deployment version.', 502);
  return parsed.data;
}
export const post = <T>(path: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, payload: unknown = {}) => api(path, schema, { method: 'POST', body: JSON.stringify(payload) });
