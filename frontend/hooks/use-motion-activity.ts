'use client';

import { useEffect, useRef, useState } from 'react';

/** One visibility gate controls CSS and canvas motion together. */
export function useMotionActivity(enabled: boolean) {
  const element = useRef<HTMLElement>(null);
  const [active, setActive] = useState(false);
  useEffect(() => {
    const root = element.current;
    if (!root) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let visible = false;
    const sync = () => setActive(enabled && visible && !document.hidden && !reduced.matches);
    const observer = new IntersectionObserver(entries => {
      visible = entries[0]?.isIntersecting ?? false;
      sync();
    });
    observer.observe(root);
    reduced.addEventListener('change', sync);
    document.addEventListener('visibilitychange', sync);
    sync();
    return () => {
      observer.disconnect();
      reduced.removeEventListener('change', sync);
      document.removeEventListener('visibilitychange', sync);
    };
  }, [enabled]);
  return { element, active };
}

