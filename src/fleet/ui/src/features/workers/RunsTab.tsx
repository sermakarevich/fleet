// Runs tab of the workers page: today's worker list on DataList +
// FilterBar with URL-synced status filters, plus the needs-attention
// strip above the list. Rendered by WorkersPage when ?tab=runs (default).
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
import { NeedsAttentionStrip } from './NeedsAttentionStrip';
import { WORKER_FILTERS, useWorkerFilters } from './useWorkerFilters';
import { TaskCard, taskColumns, type WorkerActionVerb } from './workerColumns';

interface TasksSocketMessage {
  task_id: string;
  event: FleetEvent;
}

// Closed-task window behind GET /api/tasks ?closed_limit=: the done and
// failed filters only see this many recently-closed beads, so the tab
// offers Load more up to the server max. Mirrors core/limits.py
// (CLOSED_TASKS_DEFAULT / CLOSED_TASKS_MAX).
const CLOSED_WINDOW_DEFAULT = 300;
const CLOSED_WINDOW_MAX = 2000;
const CLOSED_WINDOW_STEP = 300;

// Runs list: filters, strip, table/cards, pagination and the shared
// kill/retry/close confirm flow (mutations fire in the row cells).
export function RunsTab() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [confirming, setConfirming] = useState<{ id: string; verb: WorkerActionVerb } | null>(null);
  const [stoppingIds, setStoppingIds] = useState<Set<string>>(new Set());

  const [closedLimit, setClosedLimit] = useState<number | undefined>(undefined);
  const { data: polledTasks, isLoading, error } = useTasks(closedLimit);
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
    pageItems,
    alertCounts,
    setFilter,
    setSearchQuery,
    setPage,
  } = useWorkerFilters(tasks);

  useEffect(() => {
    setStoppingIds(prev => {
      if (prev.size === 0) return prev;
      const next = new Set([...prev].filter(id => tasks.find(t => t.id === id)?.status === 'in_progress'));
      return next.size === prev.size ? prev : next;
    });
  }, [tasks]);

  // Kill runs through the page (stopping label); retry/close mutations
  // already fired in the row cell, so every verb just clears the confirm.
  const handleActionConfirm = (id: string, verb: WorkerActionVerb) => {
    if (verb === 'Kill') {
      void killTask.mutateAsync(id)
        .then(() => setStoppingIds(prev => new Set([...prev, id])))
        .finally(() => setConfirming(null));
    } else {
      setConfirming(null);
    }
  };

  const cb = {
    confirming,
    stoppingIds,
    onActionClick: (id: string, verb: WorkerActionVerb) => setConfirming({ id, verb }),
    onActionConfirm: handleActionConfirm,
    onActionCancel: () => setConfirming(null),
  };
  const columns = taskColumns(cb);

  const windowSize = closedLimit ?? CLOSED_WINDOW_DEFAULT;
  const canLoadMore =
    (filter === 'done' || filter === 'failed') && windowSize < CLOSED_WINDOW_MAX;

  if (error && tasks.length === 0) {
    return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  }

  return (
    <>
      <NeedsAttentionStrip
        tasks={tasks}
        onSelectBlocked={() => setFilter('blocked')}
        onSelectFailed={() => setFilter('failed')}
      />
      <div style={R.topBarStyle()}>
        <FilterBar
          searchQuery={searchQuery}
          onSearchQuery={setSearchQuery}
          searchWidth={isMobile ? '100%' : '13rem'}
          filters={WORKER_FILTERS.map(({ key, label }) => ({
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
          onRowClick={(task) => navigate(`/workers/${task.id}`)}
          renderCard={(task) => <TaskCard task={task} cb={cb} />}
          empty="No workers match this filter."
        />
      )}

      {canLoadMore && (
        <div style={R.paginationStyle()}>
          <span style={R.pageInfoStyle()}>
            Showing up to {windowSize} closed workers
          </span>
          <button
            style={R.pageBtnStyle(false)}
            onClick={() => setClosedLimit(Math.min(CLOSED_WINDOW_MAX, windowSize + CLOSED_WINDOW_STEP))}
          >
            Load more
          </button>
        </div>
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
    </>
  );
}
