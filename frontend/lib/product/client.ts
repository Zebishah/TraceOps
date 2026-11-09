import { z } from 'zod';
import { verificationRequiredSchema } from './auth-contracts.ts';
import { rememberVerification } from './verification-flow.ts';
import { dashboardCache, dashboardCacheKey, organizationScope, connectDashboardCache } from './dashboard-cache.ts';

export class ApiError extends Error {
  verification: z.infer<typeof verificationRequiredSchema> | null = null;
  status: number; requestId: string | null; code: string | null; retryAfter: number | null;
  constructor(message: string, status: number, requestId: string | null = null, code: string | null = null, retryAfter: number | null = null) {
    super(message); this.name = 'ApiError'; this.status = status; this.requestId = requestId;
    this.code = code; this.retryAfter = retryAfter;
  }
}
async function request<T>(path: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(`/api/backend/${path}`, { ...init, headers, credentials: 'same-origin', cache: 'no-store' });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new ApiError('We couldn’t connect to TraceOps. Check your connection and try again.', 0);
  }
  const requestId = response.headers.get('x-request-id');
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    let message = response.status >= 500
      ? 'TraceOps couldn’t complete the request. Please try again shortly.'
      : response.status === 429
        ? 'Too many requests. Wait a moment and try again.'
        : 'The request could not be completed. Please try again.';
    let code: string | null = null;
    let verificationDetails: z.infer<typeof verificationRequiredSchema> | null = null;
    if (response.status < 500 && typeof data === 'object' && data !== null && 'detail' in data) {
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
      } else if (typeof data.detail === 'string' && data.detail.trim()) message = data.detail.trim();
      else if (Array.isArray(data.detail)) message = 'Please check the submitted fields.';
    }
    const retry = response.headers.get('retry-after'); const seconds = retry === null ? NaN : Number(retry);
    if (typeof window !== 'undefined' && (response.status === 401 || response.status === 403)) dashboardCache.invalidate('*', false, false);
    if (typeof window !== 'undefined' && response.status >= 400 && response.status < 500 && response.status !== 429) {
      const readKey = dashboardCacheKey(path); if (readKey) dashboardCache.refresh(readKey);
    }
    const error = new ApiError(message, response.status, requestId, code, Number.isFinite(seconds) && seconds > 0 ? Math.min(86400, Math.ceil(seconds)) : null);
    error.verification = verificationDetails;
    throw error;
  }
  const parsed = schema.safeParse(data);
  if (!parsed.success) throw new ApiError('TraceOps returned an unexpected response. Refresh the page and try again.', 502, requestId);
  if (typeof window !== 'undefined' && path === 'auth/me') {
    const identity = z.object({ user: z.object({ id: z.string() }), memberships: z.array(z.object({ organization_id: z.string(), role: z.string() })) }).safeParse(parsed.data);
    if (identity.success) dashboardCache.setPrincipal(JSON.stringify([identity.data.user.id, identity.data.memberships.map(m => `${m.organization_id}:${m.role}`).sort()]));
  }
  return parsed.data;
}
export async function api<T>(path: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, init: RequestInit = {}): Promise<T> {
  const browser = typeof window !== 'undefined';
  const method = (init.method ?? 'GET').toUpperCase();
  const key = browser && method === 'GET' ? dashboardCacheKey(path) : null;
  if (browser) connectDashboardCache();
  if (key) return dashboardCache.load(key, (signal, force) => {
    const headers = new Headers(init.headers);
    if (force) headers.set('X-OpsPilot-Refresh', '1');
    return request(path, schema, { ...init, headers, signal });
  }, init.signal);
  // These POST endpoints only search existing data. Do not invalidate on every keystroke.
  const readOperation = /\/(?:answers|retrieval\/search|dashboard\/project-knowledge|voice\/(?:transcriptions|speech))$/.test(path);
  const scope = organizationScope(path);
  const mutation = browser && method !== 'GET' && method !== 'HEAD' && scope !== null && !readOperation;
  if (mutation) dashboardCache.invalidate(scope);
  try { return await request(path, schema, init); }
  finally { if (mutation) dashboardCache.invalidate(scope); }
}
export const post = <T>(path: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, payload: unknown = {}) => api(path, schema, { method: 'POST', body: JSON.stringify(payload) });
