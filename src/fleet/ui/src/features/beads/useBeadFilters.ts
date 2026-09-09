/**
 * Filter state for the beads page, synced to the URL query string.
 * Owns the status filter, search query and page; derives the filtered,
 * sorted and paginated bead lists. Built on useUrlFilters (ADR 0009
 * rule 2). Called by BeadsPage; tested by useBeadFilters.test.ts.
 */
import { useMemo } from 'react';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
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

const VALID = BEAD_FILTERS.map((f) => f.key);

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
  const {
    status: statusFilter,
    searchQuery,
    page,
    setStatus: setStatusFilter,
    setSearchQuery,
    setPage,
  } = useUrlFilters<BeadStatusFilter>({ valid: VALID, defaultStatus: 'in_progress' });

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
    setStatusFilter,
    setSearchQuery,
    setPage,
  };
}
