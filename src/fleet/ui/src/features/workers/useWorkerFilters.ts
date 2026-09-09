/**
 * Filter state for the workers page Runs tab: status filter, search query
 * and page, plus the filtered, sorted and paginated worker lists. State
 * lives in the URL (ADR 0009 rule 2) via useUrlFilters so the list is
 * shareable. Called by WorkersPage.
 */
import { useMemo } from 'react';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
import type { TaskSummary } from '../../shared/types';

export type WorkerStatusFilter = 'running' | 'queued' | 'blocked' | 'done' | 'failed';

export const WORKER_FILTERS: Array<{ key: WorkerStatusFilter; label: string }> = [
  { key: 'running', label: 'Running' },
  { key: 'queued', label: 'Queued' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'done', label: 'Done' },
  { key: 'failed', label: 'Failed' },
];

export const WORKERS_PAGE_SIZE = 25;

const VALID = WORKER_FILTERS.map((f) => f.key);

const ALERT_FILTERS: WorkerStatusFilter[] = ['blocked', 'failed'];

// Keep workers matching the status filter and search query.
function applyFilter(tasks: TaskSummary[], filter: WorkerStatusFilter, query: string): TaskSummary[] {
  const q = query.trim().toLowerCase();
  return tasks.filter((task) => {
    if (!matchesFilter(task, filter)) return false;
    if (!q) return true;
    return (
      (task.id ?? '').toLowerCase().includes(q) ||
      (task.title ?? '').toLowerCase().includes(q) ||
      (task.cwd ?? '').toLowerCase().includes(q)
    );
  });
}

function matchesFilter(task: TaskSummary, filter: WorkerStatusFilter): boolean {
  switch (filter) {
    case 'running': return task.status === 'in_progress';
    case 'queued': return task.status === 'open' || task.status === 'ready';
    case 'blocked': return task.status === 'blocked';
    case 'done': return task.status === 'closed';
    case 'failed': return task.status === 'failed';
  }
}

// Newest workers first by creation/start timestamp.
function sortTasks(tasks: TaskSummary[]): TaskSummary[] {
  return [...tasks].sort((a, b) => {
    const aTs = a.created_at ?? a.started_at ?? '';
    const bTs = b.created_at ?? b.started_at ?? '';
    return bTs.localeCompare(aTs);
  });
}

// Filter state + derived lists for the workers page Runs tab.
export function useWorkerFilters(tasks: TaskSummary[]) {
  const {
    status: filter,
    searchQuery,
    page,
    setStatus: setFilter,
    setSearchQuery,
    setPage,
  } = useUrlFilters<WorkerStatusFilter>({ valid: VALID, defaultStatus: 'running' });

  const sortedFiltered = useMemo(
    () => sortTasks(applyFilter(tasks, filter, searchQuery)),
    [tasks, filter, searchQuery],
  );
  const totalPages = Math.max(1, Math.ceil(sortedFiltered.length / WORKERS_PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const pageItems = sortedFiltered.slice(safePage * WORKERS_PAGE_SIZE, (safePage + 1) * WORKERS_PAGE_SIZE);

  const alertCounts = useMemo(() => {
    const counts: Partial<Record<WorkerStatusFilter, number>> = {};
    for (const key of ALERT_FILTERS) {
      counts[key] = tasks.filter((t) => matchesFilter(t, key)).length;
    }
    return counts;
  }, [tasks]);

  return {
    filter,
    searchQuery,
    page: safePage,
    totalPages,
    sortedFiltered,
    pageItems,
    alertCounts,
    setFilter,
    setSearchQuery,
    setPage,
  };
}
