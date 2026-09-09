// Shared viewport hook: true below the breakpoint (default 700px).
// Rendered lists (via DataList) switch between table and card layouts.
// Falls back to window.innerWidth where matchMedia is unavailable
// (jsdom tests) so callers never need to mock it.
import { useEffect, useState } from 'react';

export function useIsMobile(breakpoint = 700): boolean {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < breakpoint,
  );
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [breakpoint]);
  return isMobile;
}
