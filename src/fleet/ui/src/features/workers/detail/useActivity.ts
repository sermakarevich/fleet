// Activity feed hook (ADR 0017): tail + 2s cursor polling while in
// progress, one final fetch after finish. Own setInterval — never
// usePoll/react-query here (their interval is tied to the global socket).
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../../../shared/api';
import type { ActivityItem, ActivityStderr } from '../../../shared/types';

export interface ActivityState {
  items: ActivityItem[]; // ascending seq, deduplicated by seq
  stderr: ActivityStderr | null;
  latestAttempt: number;
  hasEarlier: boolean;
  error: string | null; // last fetch error message, cleared on success
  loading: boolean; // true only before the first successful load
  lastUpdated: number | null; // Date.now() of the last successful fetch
  loadEarlier(): void; // fetch `before = items[0].seq`, prepend
  retry(): void;
}

const TAIL_LIMIT = 200;
const MAX_ITEMS = 5000;
const POLL_MS = 2000;

function mergeAsc(existing: ActivityItem[], incoming: ActivityItem[]): ActivityItem[] {
  if (incoming.length === 0) return existing;
  const seen = new Set(existing.map((i) => i.seq));
  const fresh = incoming.filter((i) => !seen.has(i.seq));
  if (fresh.length === 0) return existing;
  return [...existing, ...fresh].sort((a, b) => a.seq - b.seq);
}

function cap(items: ActivityItem[]): { items: ActivityItem[]; trimmed: boolean } {
  if (items.length > MAX_ITEMS) return { items: items.slice(items.length - MAX_ITEMS), trimmed: true };
  return { items, trimmed: false };
}

export function useActivity(taskId: string, status: string, minLevel = 'warning'): ActivityState {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [stderr, setStderr] = useState<ActivityStderr | null>(null);
  const [latestAttempt, setLatestAttempt] = useState(1);
  const [hasEarlier, setHasEarlier] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  const itemsRef = useRef<ActivityItem[]>([]);
  itemsRef.current = items;
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const taskIdRef = useRef(taskId);
  taskIdRef.current = taskId;
  const minLevelRef = useRef(minLevel);
  minLevelRef.current = minLevel;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  function applySuccess(
    res: { items: ActivityItem[]; stderr: ActivityStderr | null; latest_attempt: number; has_earlier: boolean },
    mode: 'tail' | 'append' | 'prepend',
  ): void {
    const incoming = [...res.items].sort((a, b) => a.seq - b.seq);
    if (mode === 'tail') {
      const capped = cap(incoming);
      setItems(capped.items);
      itemsRef.current = capped.items;
      setHasEarlier(res.has_earlier || capped.trimmed);
    } else if (mode === 'append') {
      const merged = mergeAsc(itemsRef.current, incoming);
      const capped = cap(merged);
      setItems(capped.items);
      itemsRef.current = capped.items;
      if (capped.trimmed) setHasEarlier(true);
    } else {
      const seen = new Set(itemsRef.current.map((i) => i.seq));
      const fresh = incoming.filter((i) => !seen.has(i.seq));
      const merged = [...fresh, ...itemsRef.current].sort((a, b) => a.seq - b.seq);
      const capped = cap(merged);
      setItems(capped.items);
      itemsRef.current = capped.items;
      setHasEarlier(res.has_earlier || capped.trimmed);
    }
    setStderr(res.stderr);
    setLatestAttempt(res.latest_attempt);
    setError(null);
    setLastUpdated(Date.now());
    setLoading(false);
  }

  function applyFailure(err: unknown): void {
    if (!mounted.current) return;
    setError(errorMessage(err));
    setLoading(false);
  }

  // Reset + tail fetch whenever taskId or minLevel changes.
  useEffect(() => {
    setItems([]);
    itemsRef.current = [];
    setStderr(null);
    setLatestAttempt(1);
    setHasEarlier(false);
    setError(null);
    setLoading(true);
    setLastUpdated(null);

    let cancelled = false;
    async function tail(): Promise<void> {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const res = await api.getActivity(taskId, { limit: TAIL_LIMIT, minLevel });
        if (cancelled || !mounted.current) return;
        applySuccess(res, 'tail');
      } catch (err) {
        if (cancelled || !mounted.current) return;
        applyFailure(err);
      } finally {
        inFlight.current = false;
      }
    }
    void tail();
    return () => {
      cancelled = true;
    };
  }, [taskId, minLevel]);

  // Polling while in_progress; one final delta fetch when status flips away
  // from in_progress, then stop. The mount tail covers the initial load, so
  // the final fetch only fires on an actual status change.
  const prevRef = useRef<{ key: string; status: string | null } | null>(null);
  useEffect(() => {
    const key = `${taskId}|${minLevel}`;
    const was = prevRef.current && prevRef.current.key === key ? prevRef.current.status : null;
    prevRef.current = { key, status };
    if (status === 'in_progress') {
      const id = setInterval(() => {
        void (async () => {
          if (inFlight.current || !mounted.current) return;
          inFlight.current = true;
          try {
            const current = itemsRef.current;
            const res =
              current.length === 0
                ? await api.getActivity(taskIdRef.current, {
                    limit: TAIL_LIMIT,
                    minLevel: minLevelRef.current,
                  })
                : await api.getActivity(taskIdRef.current, {
                    after: current[current.length - 1].seq,
                    limit: TAIL_LIMIT,
                    minLevel: minLevelRef.current,
                  });
            if (!mounted.current) return;
            applySuccess(res, current.length === 0 ? 'tail' : 'append');
          } catch (err) {
            if (!mounted.current) return;
            applyFailure(err);
          } finally {
            inFlight.current = false;
          }
        })();
      }, POLL_MS);
      return () => clearInterval(id);
    }
    // Non-in-progress: final fetch only after a real transition (was
    // in_progress). On mount (was === null) the tail above already loaded.
    if (was !== 'in_progress') return;
    let cancelled = false;
    void (async () => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const current = itemsRef.current;
        const res =
          current.length === 0
            ? await api.getActivity(taskId, { limit: TAIL_LIMIT, minLevel })
            : await api.getActivity(taskId, {
                after: current[current.length - 1].seq,
                limit: TAIL_LIMIT,
                minLevel,
              });
        if (cancelled || !mounted.current) return;
        applySuccess(res, current.length === 0 ? 'tail' : 'append');
      } catch (err) {
        if (cancelled || !mounted.current) return;
        applyFailure(err);
      } finally {
        inFlight.current = false;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [taskId, status, minLevel]);

  const loadEarlier = useCallback(() => {
    void (async () => {
      const first = itemsRef.current[0];
      if (!first || inFlight.current || !mounted.current) return;
      inFlight.current = true;
      try {
        const res = await api.getActivity(taskIdRef.current, {
          before: first.seq,
          limit: TAIL_LIMIT,
          minLevel: minLevelRef.current,
        });
        if (!mounted.current) return;
        applySuccess(res, 'prepend');
      } catch (err) {
        if (!mounted.current) return;
        applyFailure(err);
      } finally {
        inFlight.current = false;
      }
    })();
  }, []);

  const retry = useCallback(() => {
    void (async () => {
      if (inFlight.current || !mounted.current) return;
      inFlight.current = true;
      try {
        const current = itemsRef.current;
        const res =
          current.length === 0
            ? await api.getActivity(taskIdRef.current, {
                limit: TAIL_LIMIT,
                minLevel: minLevelRef.current,
              })
            : await api.getActivity(taskIdRef.current, {
                after: current[current.length - 1].seq,
                limit: TAIL_LIMIT,
                minLevel: minLevelRef.current,
              });
        if (!mounted.current) return;
        applySuccess(res, current.length === 0 ? 'tail' : 'append');
      } catch (err) {
        if (!mounted.current) return;
        applyFailure(err);
      } finally {
        inFlight.current = false;
      }
    })();
  }, []);

  return { items, stderr, latestAttempt, hasEarlier, error, loading, lastUpdated, loadEarlier, retry };
}
