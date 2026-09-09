/**
 * URL-synced list filter state: search query (`q`), status filter
 * (`status`) and page (`page`) read/written through useSearchParams so
 * every list URL is shareable. Generic over the status union; feature
 * hooks (tasks, beads) wrap it with their own filter vocabulary and
 * derived lists. Rendered by FilterBar.
 */
import { useSearchParams } from 'react-router-dom';

interface UseUrlFiltersOptions<T extends string> {
  /** All valid status keys for this list. */
  valid: readonly T[];
  /** Status assumed when the URL has none (or an unknown one). */
  defaultStatus: T;
  /** URL key for the status; defaults to `status`. */
  statusKey?: string;
}

// Read a non-negative page number from the URL.
function parsePage(params: URLSearchParams): number {
  const raw = Number(params.get('page'));
  return Number.isInteger(raw) && raw >= 0 ? raw : 0;
}

// Filter state for one list, synced to the URL query string.
export function useUrlFilters<T extends string>({
  valid,
  defaultStatus,
  statusKey = 'status',
}: UseUrlFiltersOptions<T>) {
  const [params, setParams] = useSearchParams();
  const rawStatus = params.get(statusKey);
  const status: T =
    rawStatus && (valid as readonly string[]).includes(rawStatus)
      ? (rawStatus as T)
      : defaultStatus;
  const searchQuery = params.get('q') ?? '';
  const page = parsePage(params);

  function update(patch: Record<string, string>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next, { replace: true });
  }

  return {
    status,
    searchQuery,
    page,
    setStatus: (s: T) => update({ [statusKey]: s === defaultStatus ? '' : s, page: '' }),
    setSearchQuery: (q: string) => update({ q, page: '' }),
    setPage: (p: number) => update({ page: p > 0 ? String(p) : '' }),
  };
}
