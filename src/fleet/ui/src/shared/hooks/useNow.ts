/**
 * The one ticking clock in the UI (1 s). Called by InboxPage (which passes
 * `now` down so the whole tree ticks together) and ActivityGutter;
 * relative-time text comes from formatRelativeAge in shared/format.ts.
 */
import { useEffect, useState } from 'react';

// Re-render the caller every intervalMs; returns the current epoch millis.
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
