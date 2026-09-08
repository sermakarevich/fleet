/**
 * Filter state for the beads page, synced to the URL query string.
 * Owns the status filter, search query and page; derives the filtered,
 * sorted and paginated bead lists. Called by BeadsPage;
 * tested by useBeadFilters.test.ts.
 */
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { Bead } from '../../shared/types';

export type BeadStatusFilter = 'all' | 'open' | 'in_progress' | 'blocked' | 'deferred' | 'closed';

export const BEAD_FILTERS: Array<{ key: BeadStatusFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'open', label: 'Open' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'deferred', label: 'Deferred' },
  { key: 'closed', label: 'Closed' },
];

export const BEAD_PAGE_SIZE = 25;

const VALID_STATUSES = new Set<string>(BEAD_FILTERS.map((f) => f.key));

// Read the status filter from the URL, defaulting to in_progress.
function parseStatusFilter(params: URLSearchParams): BeadStatusFilter {
  const raw = params.get('status');
  return raw && VALID_STATUSES.has(raw) ? (raw as BeadStatusFilter) : 'in_progress';
}

// Read a non-negative page number from the URL.
function parsePage(params: URLSearchParams): number {
  const raw = Number(params.get('page'));
  return Number.isInteger(raw) && raw >= 0 ? raw : 0;
}

// Keep beads matching the status filter and search query.
function applyFilter(beads: Bead[], status: BeadStatusFilter, query: string): Bead[] {
  const q = query.trim().toLowerCase();
  return beads.filter((b) => {
    if (status !== 'all' && b.status !== status) return false;
    if (!q) return true;
    return (
      b.id.toLowerCase().includes(q) ||
      b.title.toLowerCase().includes(q) ||
      (b.assignee ?? '').toLowerCase().includes(q)
    );
  });
}

// Newest beads first, ties broken by id.
function sortBeads(beads: Bead[]): Bead[] {
  return [...beads].sort(
    (a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '') || a.id.localeCompare(b.id),
  );
}

// Filter state + URL sync + derived lists for the beads page.
export function useBeadFilters(beads: Bead[] | undefined) {
  const [params, setParams] = useSearchParams();
  const statusFilter = parseStatusFilter(params);
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

  const sorted = useMemo(
    () => sortBeads(applyFilter(beads ?? [], statusFilter, searchQuery)),
    [beads, statusFilter, searchQuery],
  );
  const totalPages = Math.max(1, Math.ceil(sorted.length / BEAD_PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const pageItems = sorted.slice(safePage * BEAD_PAGE_SIZE, (safePage + 1) * BEAD_PAGE_SIZE);

  return {
    statusFilter,
    searchQuery,
    page: safePage,
    totalPages,
    sorted,
    pageItems,
    setStatusFilter: (s: BeadStatusFilter) => update({ status: s === 'in_progress' ? '' : s, page: '' }),
    setSearchQuery: (q: string) => update({ q, page: '' }),
    setPage: (p: number) => update({ page: p > 0 ? String(p) : '' }),
  };
}
