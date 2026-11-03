export const SESSION_COOKIE = 'opspilot_backend_session';
export const MAX_REQUEST_BYTES = 11 * 1024 * 1024;
const UUID = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const paths = [
  /^auth\/(login|register|me|mcp-token)$/,
  /^health(?:\/ready)?$/,
  new RegExp(`^organizations/${UUID}/(?:incidents(?:/${UUID}(?:/(?:classify|retrieve-evidence|investigate-background|acknowledge|resolve-no-action|approvals/${UUID}(?:/(?:decision|resume-status))?|investigations/${UUID}/(?:result|retry)))?)?|documents(?:/${UUID}/(?:process|chunks|index))?|jobs/${UUID}|retrieval/search|answers)$`),
  new RegExp(`^organizations/${UUID}/dashboard/(?:overview|workspace|resources/(?:incidents|documents|approvals|jobs|customers|orders|payments|memories|automations|recovery)(?:/${UUID})?|incidents/${UUID}/latest|project-knowledge|evaluations)$`),
];
export function allowedBackendPath(path: string): boolean {
  return !/[\\%?#]/.test(path) && paths.some(pattern => pattern.test(path));
}
export function sameOrigin(requestUrl: string, origin: string | null): boolean {
  return origin !== null && origin === new URL(requestUrl).origin;
}
export function cookieLifetime(token: string): number {
  try {
    const part = token.split('.')[1];
    if (!part) return 3600;
    const decoded: unknown = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')));
    if (typeof decoded === 'object' && decoded !== null && 'exp' in decoded && typeof decoded.exp === 'number') {
      return Math.max(1, Math.min(86400, Math.floor(decoded.exp - Date.now() / 1000)));
    }
  } catch { /* The upstream remains responsible for verifying the token. */ }
  return 3600;
}
