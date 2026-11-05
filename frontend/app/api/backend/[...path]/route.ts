import { cookies } from 'next/headers';
import { backendOrigin } from '@/lib/product/backend-config';
import {isVoiceSpeechPath,proxyVoiceSpeechResponse} from '@/lib/product/voice-proxy';
import { z } from 'zod';
import { anonymousAuthPath, authInputSchema, verificationRequiredSchema } from '@/lib/product/auth-contracts';
import { allowedBackendPath, cookieLifetime, MAX_REQUEST_BYTES, sameRequestOrigin, SESSION_COOKIE } from '@/lib/product/proxy-policy';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 120;
const jsonError = (detail: string, status: number) => Response.json({ detail }, { status, headers: { 'Cache-Control': 'no-store' } });
type Context = { params: Promise<{ path: string[] }> };
async function proxy(request: Request, context: Context): Promise<Response> {
  const { path: parts } = await context.params;
  const path = parts.join('/');
  if (!allowedBackendPath(path)) return jsonError('Unsupported API operation', 404);
  const write = request.method !== 'GET';
  const speech = isVoiceSpeechPath(path);
  if (/\/voice\//.test(path) && request.method !== (path.endsWith('/capabilities') ? 'GET' : 'POST')) return jsonError('Method not allowed', 405);
  if (write && !sameRequestOrigin(request)) return jsonError('Request origin rejected', 403);
  if (request.method === 'GET' && (anonymousAuthPath(path) || path === 'auth/mcp-token')) return jsonError('Method not allowed', 405);
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  const anonymous = anonymousAuthPath(path) || path === 'health';
  if (!anonymous && !token) return jsonError('Sign in to your OpsPilot account', 401);
  const headers = new Headers({ Accept: speech ? 'audio/wav, application/json' : 'application/json' });
  if (token && !anonymous) headers.set('Authorization', `Bearer ${token}`);
  let body: ArrayBuffer | undefined;
  if (write) {
    if (Number(request.headers.get('content-length') ?? 0) > MAX_REQUEST_BYTES) return jsonError('Request exceeds the upload limit', 413);
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_REQUEST_BYTES) return jsonError('Request exceeds the upload limit', 413);
    const contentType = request.headers.get('content-type') ?? 'application/json';
    headers.set('Content-Type', contentType);
    const schema = authInputSchema(path);
    if (schema) {
      try {
        const input: unknown = JSON.parse(new TextDecoder().decode(body));
        const parsed = schema.safeParse(input);
        if (!parsed.success) return jsonError(parsed.error.issues[0]?.message ?? 'Invalid account information', 422);
        body = new TextEncoder().encode(JSON.stringify(parsed.data)).buffer;
      } catch { return jsonError('Invalid JSON request', 400); }
    }
  }
  let origin: string;
  try { origin = backendOrigin(process.env.OPSPILOT_BACKEND_URL); }
  catch (cause) { return jsonError(cause instanceof Error ? cause.message : 'Backend URL is not configured.', 503); }
  const upstreamUrl = new URL(`/api/v1/${path}`, origin);
  upstreamUrl.search = path.startsWith('auth/verification/') ? '' : new URL(request.url).search;
  try {
    const upstream = await fetch(upstreamUrl, { method: request.method, headers, body, redirect: 'manual', signal: AbortSignal.any([request.signal, AbortSignal.timeout(90000)]), cache: 'no-store' });
    // Workers support manual redirects; reject them rather than forwarding credentials.
    if (upstream.status >= 300 && upstream.status < 400) return jsonError('The backend redirected this request. Check its configured URL.', 502);
    const responseHeaders = new Headers({ 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
    for (const key of ['retry-after', 'x-request-id']) { const value = upstream.headers.get(key); if (value) responseHeaders.set(key, value); }
    if (path.startsWith('auth/')) responseHeaders.set('Referrer-Policy', 'no-referrer');
    if ((path === 'auth/login' || path === 'auth/verification/code') && upstream.ok) {
      const sessionSchema = z.object({ access_token: z.string().min(1) });
      const parsed = (path === 'auth/verification/code' ? sessionSchema.extend({ verified: z.literal(true) }) : sessionSchema).safeParse(await upstream.json());
      if (!parsed.success) return jsonError('The backend returned an invalid session', 502);
      cookieStore.set(SESSION_COOKIE, parsed.data.access_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production' || new URL(request.url).protocol === 'https:', sameSite: 'strict', path: '/', maxAge: cookieLifetime(parsed.data.access_token) });
      return Response.json({ authenticated: true, ...(path === 'auth/verification/code' ? { verified: true } : {}) }, { headers: responseHeaders });
    }
    if (upstream.status === 401) cookieStore.delete(SESSION_COOKIE);
    if (upstream.status === 403 && (upstream.headers.get('content-type') ?? '').includes('application/json')) {
      const denied: unknown = await upstream.clone().json().catch(() => null);
      if (typeof denied === 'object' && denied !== null && 'detail' in denied && verificationRequiredSchema.safeParse(denied.detail).success) cookieStore.delete(SESSION_COOKIE);
    }
    if (speech && upstream.ok) return await proxyVoiceSpeechResponse(upstream);
    if (!(upstream.headers.get('content-type') ?? '').includes('application/json')) {
      if (upstream.status === 404) return jsonError('Not Found', 404);
      if (upstream.status === 401) return jsonError('Your session expired. Please sign in again.', 401);
      if (upstream.status === 403) return jsonError('Your account cannot access this operation.', 403);
      return jsonError(`The backend returned an unexpected response (HTTP ${upstream.status}). Check the configured deployment or try again after it has started.`, 502);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch (cause) {
    const timeout = cause instanceof Error && (cause.name === 'TimeoutError' || cause.name === 'AbortError');
    return jsonError(timeout ? 'The backend took too long to respond. It may be starting up; try again shortly.' : 'Could not connect to the configured backend. Check OPSPILOT_BACKEND_URL and backend availability.', timeout ? 504 : 502);
  }
}
export const GET = proxy;
export const POST = proxy;
