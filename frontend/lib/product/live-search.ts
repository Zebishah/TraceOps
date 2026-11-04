export const SEARCH_DELAY_MS = 350;

/** A burst of edits produces one search. Explicit submission flushes that same search. */
export function createLiveSearch(search: (query: string) => void, delay = SEARCH_DELAY_MS) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let latest = '';
  const cancel = () => { if (timer !== undefined) clearTimeout(timer); timer = undefined; };
  const flush = () => { cancel(); search(latest.trim()); };
  return {
    change(value: string) { latest = value; cancel(); if (!value.trim()) flush(); else timer = setTimeout(flush, delay); },
    submit(value?: string) { if (value !== undefined) latest = value; flush(); },
    cancel,
  };
}
