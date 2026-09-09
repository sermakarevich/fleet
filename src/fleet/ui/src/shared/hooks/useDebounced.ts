/**
 * Debounced value hook: returns the latest value after it stops changing.
 * Used by the cron preview query so typing does not fire a request per
 * keystroke. Called by useCronPreview in useApi.ts.
 */
import { useEffect, useState } from 'react';

// Latest value, updated only after `delayMs` without changes.
export function useDebounced<T>(value: T, delayMs = 400): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
