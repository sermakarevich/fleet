import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useKillTask, useTasks } from '../../shared/hooks/useApi';
import { applyTaskOverlays, useTasksState } from '../../shared/hooks/useTasksState';
import { useEventSocket } from '../../shared/hooks/useEventSocket';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import type { FleetEvent } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { DataList } from '../../shared/ui/DataList';
import { FilterBar } from '../../shared/ui/FilterBar';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';
import { TASK_FILTERS, useTaskFilters } from './useTaskFilters';
import { TaskCard, taskColumns } from './taskColumns';

interface TasksSocketMessage {
  task_id: string;
  event: FleetEvent;
}

export function TasksPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [stoppingIds, setStoppingIds] = useState<Set<string>>(new Set());

  const { data: polledTasks, isLoading, error } = useTasks();
  const { overlays, updateFromEvent } = useTasksState();
  const killTask = useKillTask();

  // Displayed list derives from the polled query plus live socket
  // overlays, so polls never discard updates that arrived between polls.
  const tasks = useMemo(
    () => applyTaskOverlays(polledTasks ?? [], overlays),
    [polledTasks, overlays],
  );

  useEventSocket<TasksSocketMessage>('/ws/events', ({ task_id: taskId, event }) => {
    updateFromEvent(taskId, event);
  });

  const {
    filter,
    searchQuery,
    page,
    totalPages,
    sortedFiltered,
    pageItems,
    alertCounts,
    setFilter,
    setSearchQuery,
    setPage,
  } = useTaskFilters(tasks);

  useEffect(() => {
    setStoppingIds(prev => {
      if (prev.size === 0) return prev;
      const next = new Set([...prev].filter(id => tasks.find(t => t.id === id)?.status === 'in_progress'));
      return next.size === prev.size ? prev : next;
    });
  }, [tasks]);

  const handleKillConfirm = (id: string) => {
    void killTask.mutateAsync(id)
      .then(() => setStoppingIds(prev => new Set([...prev, id])))
      .finally(() => setConfirmingId(null));
  };

  const cb = {
    confirmingId,
    stoppingIds,
    onKillClick: (id: string) => setConfirmingId(id),
    onKillConfirm: handleKillConfirm,
    onKillCancel: () => setConfirmingId(null),
  };
  const columns = taskColumns(cb);

  if (error && tasks.length === 0) {
    return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  }

  return (
    <PageShell title="tasks" count={sortedFiltered.length}>
      <div style={R.topBarStyle()}>
        <FilterBar
          searchQuery={searchQuery}
          onSearchQuery={setSearchQuery}
          searchWidth={isMobile ? '100%' : '13rem'}
          filters={TASK_FILTERS.map(({ key, label }) => ({
            key,
            label,
            alertCount: alertCounts[key] ?? 0,
          }))}
          active={filter}
          onSelect={setFilter}
        />
      </div>

      {isLoading && tasks.length === 0 ? (
        <LoadingState />
      ) : (
        <DataList
          columns={columns}
          rows={pageItems}
          rowKey={(task) => task.id}
          onRowClick={(task) => navigate(`/tasks/${task.id}`)}
          renderCard={(task) => <TaskCard task={task} cb={cb} />}
          empty="No tasks match this filter."
        />
      )}

      {totalPages > 1 && (
        <div style={R.paginationStyle()}>
          <button
            style={R.pageBtnStyle(page === 0)}
            disabled={page === 0}
            onClick={() => setPage(Math.max(0, page - 1))}
          >
            ← Prev
          </button>
          <span style={R.pageInfoStyle()}>
            {page + 1} / {totalPages}
          </span>
          <button
            style={R.pageBtnStyle(page >= totalPages - 1)}
            disabled={page >= totalPages - 1}
            onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
          >
            Next →
          </button>
        </div>
      )}
    </PageShell>
  );
}
