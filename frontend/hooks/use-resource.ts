'use client';
import { useCallback, useEffect, useRef, useState } from 'react';

export function useResource<T>(loader: ((signal: AbortSignal) => Promise<T>) | null, deps: readonly unknown[], pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(Boolean(loader));
  const [refreshing, setRefreshing] = useState(false);
  const [version, setVersion] = useState(0);
  const saved = useRef(loader);
  const previousDeps = useRef<readonly unknown[] | null>(null);
  const currentData = useRef<T | null>(null);
  saved.current = loader;
  const refresh = useCallback(() => setVersion(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    const sameIdentity = previousDeps.current !== null && previousDeps.current.length === deps.length && deps.every((value, index) => Object.is(value, previousDeps.current?.[index]));
    previousDeps.current = [...deps];
    // A refresh keeps the current view. A changed organization/filter clears old data.
    if (!sameIdentity || !saved.current) {
      currentData.current = null;
      setData(null);
    }
    setError(null);
    setLoading(Boolean(saved.current) && currentData.current === null);
    setRefreshing(Boolean(saved.current) && currentData.current !== null);
    async function run() {
      if (!saved.current) return;
      if (pollMs && document.visibilityState === 'hidden') {
        timer = setTimeout(run, pollMs);
        return;
      }
      try {
        const value = await saved.current(controller.signal);
        if (active) { currentData.current = value; setData(value); setError(null); }
      } catch (cause) {
        if (active && !controller.signal.aborted) setError(cause instanceof Error ? cause : new Error('Request failed'));
      } finally {
        if (active) {
          setLoading(false);
          setRefreshing(false);
          if (pollMs) timer = setTimeout(run, pollMs);
        }
      }
    }
    void run();
    return () => { active = false; controller.abort(); if (timer) clearTimeout(timer); };
    // Callers supply scalar dependencies identifying the resource.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, version, pollMs]);
  return { data, error, loading, refreshing, refresh };
}
