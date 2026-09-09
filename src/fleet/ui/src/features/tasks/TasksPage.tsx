import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useKillTask, useTasks } from '../../shared/hooks/useApi';
import { applyTaskOverlays, useTasksState } from '../../shared/hooks/useTasksState';
import { useEventSocket } from '../../shared/hooks/useEventSocket';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import type { FleetEvent } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { TaskRow } from './TaskRow';
import { TaskCard } from './TaskCard';
import { TASK_FILTERS, useTaskFilters } from './useTaskFilters';
import { rowStyles } from './itemStyles';

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

  if (isLoading && tasks.length === 0) {
    return <p style={R.msgStyle()}>Loading…</p>;
  }
  if (error && tasks.length === 0) {
    return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  }

  return (
    <div style={R.pageStyle(isMobile)}>
      <div style={R.topBarStyle()}>
        <h1 style={R.headingStyle()}>tasks <span style={R.countStyle()}>({sortedFiltered.length})</span></h1>
        <input
          type="search"
          style={R.searchInputStyle(isMobile ? '100%' : '13rem')}
          placeholder="Search…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
        <div style={R.filterRowStyle()}>
          {TASK_FILTERS.map(({ key, label }) => {
            const hasAlert = (alertCounts[key] ?? 0) > 0;
            return (
              <button
                key={key}
                style={R.filterBtnStyle(filter === key)}
                onClick={() => setFilter(key)}
              >
                <span style={rowStyles.filterBtnInner}>
                  {label}
                  {hasAlert && <span style={rowStyles.alertDot} />}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div style={R.panelStyle()}>
        {!isMobile && (
          <div style={R.colHeaderStyle()}>
            <span style={rowStyles.colStatus}>Status</span>
            <span style={rowStyles.colId}>ID</span>
            <span style={rowStyles.colTitle}>Title</span>
            <span style={rowStyles.colCoder}>Coder / Model</span>
            <span style={rowStyles.colContext}>Context</span>
            <span style={rowStyles.colRuns}>Runs</span>
            <span style={rowStyles.colTs}>Started</span>
            <span style={rowStyles.colTs}>Completed</span>
            <span style={rowStyles.colCwd}>Cwd</span>
            <span style={rowStyles.colAction} />
          </div>
        )}

        {sortedFiltered.length === 0 ? (
          <p style={R.emptyStyle()}>No tasks match this filter.</p>
        ) : (
          pageItems.map(task => isMobile ? (
            <TaskCard
              key={task.id}
              task={task}
              confirmingId={confirmingId}
              stoppingIds={stoppingIds}
              onKillClick={id => setConfirmingId(id)}
              onKillConfirm={handleKillConfirm}
              onKillCancel={() => setConfirmingId(null)}
              onRowClick={id => navigate(`/tasks/${id}`)}
            />
          ) : (
            <TaskRow
              key={task.id}
              task={task}
              confirmingId={confirmingId}
              stoppingIds={stoppingIds}
              onKillClick={id => setConfirmingId(id)}
              onKillConfirm={handleKillConfirm}
              onKillCancel={() => setConfirmingId(null)}
              onRowClick={id => navigate(`/tasks/${id}`)}
            />
          ))
        )}
      </div>

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
    </div>
  );
}
