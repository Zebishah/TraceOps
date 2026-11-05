/** Session-memory display snapshots. Approval decisions, auth, and mutations never use this cache. */
const uuid = '[0-9a-fA-F-]{36}';
const dashboardPath = new RegExp(`^organizations/(${uuid})/dashboard/(?:overview|resources/(?:incidents|documents|approvals|jobs|customers|orders|payments|memories|automations|recovery)(?:/${uuid})?|incidents/${uuid}/latest)$`);
export const DASHBOARD_MAX_AGE_MS = 60_000;
export const DASHBOARD_POLL_MS = 15_000;
const MAX_ENTRIES = 100;
export type Snapshot<T> = { data: T; fetchedAt: number };
type Pending = { controller: AbortController; promise: Promise<unknown>; invalidated: boolean };

export function dashboardCacheKey(path: string): string | null {
  const [pathname, query = ''] = path.split('?');
  if (!dashboardPath.test(pathname)) return null;
  const params = new URLSearchParams(query); params.sort();
  return pathname + (params.size ? `?${params}` : '');
}
export function organizationScope(path: string): string | null {
  return /^organizations\/([0-9a-fA-F-]{36})(?:\/|$)/.exec(path)?.[1].toLowerCase() ?? null;
}

export class DashboardReadCache {
  private snapshots = new Map<string, Snapshot<unknown>>();
  private pending = new Map<string, Pending>();
  private forced = new Set<string>();
  private listeners = new Set<(scope: string) => void>();
  private principal: string | null = null;
  private now: () => number;
  private publish: (scope: string) => void;
  constructor(now = Date.now, publish: (scope: string) => void = () => {}) { this.now = now; this.publish = publish; }

  get<T>(key: string): Snapshot<T> | undefined {
    const entry = this.snapshots.get(key);
    if (!entry) return;
    if (this.now() - entry.fetchedAt >= DASHBOARD_MAX_AGE_MS) { this.snapshots.delete(key); return; }
    return entry as Snapshot<T>;
  }
  subscribe(listener: (scope: string) => void): () => void {
    this.listeners.add(listener); return () => { this.listeners.delete(listener); };
  }
  setPrincipal(id: string): void {
    if (this.principal !== null && this.principal !== id) this.invalidate('*');
    this.principal = id;
  }
  private forget(key: string): void {
    this.snapshots.delete(key);
    const pending = this.pending.get(key);
    if (pending) { pending.invalidated = true; this.pending.delete(key); pending.controller.abort(); }
  }
  invalidate(scope: string, publish = true, notify = true): void {
    const keys = new Set([...this.snapshots.keys(), ...this.pending.keys()]);
    for (const key of keys) if (scope === '*' || organizationScope(key) === scope) this.forget(key);
    if (scope === '*') { this.principal = null; this.forced.clear(); }
    if (notify) for (const listener of this.listeners) listener(scope);
    if (publish) this.publish(scope);
  }
  refresh(key: string): void { this.forget(key); this.forced.add(key); }
  async load<T>(key: string, loader: (signal: AbortSignal, force: boolean) => Promise<T>, consumer?: AbortSignal | null): Promise<T> {
    if (consumer?.aborted) throw new DOMException('Read cancelled', 'AbortError');
    let pending = this.pending.get(key);
    if (!pending) {
      const controller = new AbortController();
      const force = this.forced.delete(key);
      const entry: Pending = { controller, promise: Promise.resolve(), invalidated: false };
      // A quick tab switch can unmount a consumer; finish the shared read for the next visit.
      entry.promise = loader(AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]), force).then(data => {
        if (entry.invalidated) throw new DOMException('Read invalidated', 'AbortError');
        this.snapshots.delete(key);
        this.snapshots.set(key, { data, fetchedAt: this.now() });
        while (this.snapshots.size > MAX_ENTRIES) this.snapshots.delete(this.snapshots.keys().next().value!);
        return data;
      }).finally(() => { if (this.pending.get(key) === entry) this.pending.delete(key); });
      this.pending.set(key, entry); pending = entry;
    }
    const data = await pending.promise;
    if (consumer?.aborted) throw new DOMException('Read cancelled', 'AbortError');
    return data as T;
  }
}

let channel: BroadcastChannel | null = null;
function ensureChannel(): BroadcastChannel | null {
  if (!channel && typeof window !== 'undefined' && typeof BroadcastChannel !== 'undefined') {
    channel = new BroadcastChannel('opspilot.dashboard-invalidation');
    channel.onmessage = event => {
      const scope: unknown = event.data?.scope;
      if (typeof scope === 'string' && (scope === '*' || /^[0-9a-f-]{36}$/.test(scope))) dashboardCache.invalidate(scope, false);
    };
  }
  return channel;
}
export const dashboardCache = new DashboardReadCache(Date.now, scope => ensureChannel()?.postMessage({ scope }));
export function connectDashboardCache(): void { ensureChannel(); }
