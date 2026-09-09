/**
 * Filter state for the tasks page: status filter, search query and page,
 * plus the filtered, sorted and paginated task lists. State lives in the
 * URL (ADR 0009 rule 2) via useUrlFilters so the list is shareable.
 * Called by TasksPage.
 */
import { useMemo } from 'react';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
import type { TaskSummary } from '../../shared/types';

export type TaskStatusFilter = 'all' | 'running' | 'pending' | 'blocked' | 'done' | 'failed';

export const TASK_FILTERS: Array<{ key: TaskStatusFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'pending', label: 'Pending' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'done', label: 'Done' },
  { key: 'failed', label: 'Failed' },
];

export const TASKS_PAGE_SIZE = 25;

const VALID = TASK_FILTERS.map((f) => f.key);

const ALERT_FILTERS: TaskStatusFilter[] = ['blocked', 'failed'];

// Keep tasks matching the status filter and search query.
function applyFilter(tasks: TaskSummary[], filter: TaskStatusFilter, query: string): TaskSummary[] {
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

function matchesFilter(task: TaskSummary, filter: TaskStatusFilter): boolean {
  switch (filter) {
    case 'all': return true;
    case 'running': return task.status === 'in_progress';
    case 'pending': return task.status === 'open' || task.status === 'ready';
    case 'blocked': return task.status === 'blocked';
    case 'done': return task.status === 'closed';
    case 'failed': return task.status === 'failed';
  }
}

// Newest tasks first by creation/start timestamp.
function sortTasks(tasks: TaskSummary[]): TaskSummary[] {
  return [...tasks].sort((a, b) => {
    const aTs = a.created_at ?? a.started_at ?? '';
    const bTs = b.created_at ?? b.started_at ?? '';
    return bTs.localeCompare(aTs);
  });
}

// Filter state + derived lists for the tasks page.
export function useTaskFilters(tasks: TaskSummary[]) {
  const {
    status: filter,
    searchQuery,
    page,
    setStatus: setFilter,
    setSearchQuery,
    setPage,
  } = useUrlFilters<TaskStatusFilter>({ valid: VALID, defaultStatus: 'running' });

  const sortedFiltered = useMemo(
    () => sortTasks(applyFilter(tasks, filter, searchQuery)),
    [tasks, filter, searchQuery],
  );
  const totalPages = Math.max(1, Math.ceil(sortedFiltered.length / TASKS_PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const pageItems = sortedFiltered.slice(safePage * TASKS_PAGE_SIZE, (safePage + 1) * TASKS_PAGE_SIZE);

  const alertCounts = useMemo(() => {
    const counts: Partial<Record<TaskStatusFilter, number>> = {};
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
