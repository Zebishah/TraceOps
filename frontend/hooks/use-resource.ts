'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { dashboardCache, dashboardCacheKey, organizationScope, DASHBOARD_POLL_MS } from '@/lib/product/dashboard-cache';

export function useResource<T>(loader: ((signal: AbortSignal) => Promise<T>) | null, deps: readonly unknown[], pollMs = 0, cachePath?: string | null) {
  const cacheKey = cachePath ? dashboardCacheKey(cachePath) : null;
  const snapshot = loader && cacheKey ? dashboardCache.get<T>(cacheKey) : undefined;
  const [data, setData] = useState<T | null>(snapshot?.data ?? null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(Boolean(loader) && !snapshot);
  const [refreshing, setRefreshing] = useState(false);
  const [version, setVersion] = useState(0);
  const saved = useRef(loader);
  const previousDeps = useRef<readonly unknown[] | null>(null);
  const previousCacheKey = useRef(cacheKey);
  const currentData = useRef<T | null>(snapshot?.data ?? null);
  const [identity, setIdentity] = useState(() => ({ deps: [...deps], key: cacheKey }));
  const effectivePoll = pollMs || (cacheKey ? DASHBOARD_POLL_MS : 0);
  const sameView = identity.key === cacheKey && identity.deps.length === deps.length && deps.every((value, index) => Object.is(value, identity.deps[index]));
  if (!sameView) {
    setIdentity({ deps: [...deps], key: cacheKey });
    setData(snapshot?.data ?? null); setError(null); setLoading(Boolean(loader) && !snapshot);
  }
  useEffect(() => { saved.current = loader; });
  const refresh = useCallback(() => { if (cacheKey) dashboardCache.refresh(cacheKey); setVersion(value => value + 1); }, [cacheKey]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    const sameIdentity = previousCacheKey.current === cacheKey && previousDeps.current !== null && previousDeps.current.length === deps.length && deps.every((value, index) => Object.is(value, previousDeps.current?.[index]));
    previousDeps.current = [...deps];
    previousCacheKey.current = cacheKey;
    // A refresh keeps the current view. A changed organization/filter clears old data.
    if (!sameIdentity || !saved.current) {
      const cached = saved.current && cacheKey ? dashboardCache.get<T>(cacheKey) : undefined;
      currentData.current = cached?.data ?? null;
      setData(cached?.data ?? null);
    }
    setError(null);
    setLoading(Boolean(saved.current) && currentData.current === null);
    setRefreshing(Boolean(saved.current) && currentData.current !== null);
    async function run() {
      if (!saved.current) return;
      if (effectivePoll && document.visibilityState === 'hidden') {
        timer = setTimeout(run, effectivePoll);
        return;
      }
      try {
        const value = await saved.current(controller.signal);
        if (active) { currentData.current = value; setData(value); setError(null); }
      } catch (cause) {
        if (active && !controller.signal.aborted) {
          if (cacheKey && cause instanceof Error && cause.name === 'AbortError') return;
          const retained = cacheKey ? dashboardCache.get<T>(cacheKey) : undefined;
          if (!retained) {
            if (cacheKey) { currentData.current = null; setData(null); }
            setError(cause instanceof Error ? cause : new Error('Request failed'));
          }
        }
      } finally {
        if (active) {
          setLoading(false);
          setRefreshing(false);
          if (effectivePoll) timer = setTimeout(run, effectivePoll);
        }
      }
    }
    const revalidate = () => { if (document.visibilityState !== 'hidden') setVersion(value => value + 1); };
    const unsubscribe = cacheKey ? dashboardCache.subscribe(scope => {
      if (scope === '*' || organizationScope(cacheKey) === scope) revalidate();
    }) : () => {};
    if (cacheKey) { window.addEventListener('focus', revalidate); document.addEventListener('visibilitychange', revalidate); }
    void run();
    return () => {
      active = false; controller.abort(); if (timer) clearTimeout(timer); unsubscribe();
      if (cacheKey) { window.removeEventListener('focus', revalidate); document.removeEventListener('visibilitychange', revalidate); }
    };
    // Callers supply scalar dependencies identifying the resource.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, version, effectivePoll, cacheKey]);
  return { data: sameView ? data : snapshot?.data ?? null, error: sameView ? error : null, loading: sameView ? loading : Boolean(loader) && !snapshot, refreshing, refresh };
}
