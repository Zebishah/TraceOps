/** Validate the server-configured backend origin. Never accept it from a request. */
export function backendOrigin(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error('Set OPSPILOT_BACKEND_URL in frontend/.env.local and restart the frontend.');
  }
  let url: URL;
  try { url = new URL(value.trim()); }
  catch { throw new Error('OPSPILOT_BACKEND_URL must be a complete backend URL.'); }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.username || url.password || url.search || url.hash || !['/', '/api/v1', '/api/v1/'].includes(url.pathname) || !(url.protocol === 'https:' || (url.protocol === 'http:' && loopback))) {
    throw new Error('OPSPILOT_BACKEND_URL must use HTTPS, or HTTP on localhost, without credentials, query strings, or a custom path.');
  }
  return url.origin;
}

/** Leave room for multipart metadata below Vercel's 4.5 MB function payload limit. */
export function frontendUploadLimit(vercel: unknown): number {
  return (vercel === '1' ? 4 : 10) * 1024 * 1024;
}
