import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useKillTask, useTasks } from '../../shared/hooks/useApi';
import { useTasksState } from '../../shared/hooks/useTasksState';
import { useWebSocket } from '../../shared/hooks/useWebSocket';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import type { TaskSummary } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { TaskRow } from './TaskRow';
import { TaskCard } from './TaskCard';
import { styles } from './itemStyles';

type StatusFilter = 'all' | 'running' | 'pending' | 'blocked' | 'done' | 'failed';

const FILTERS: Array<{ key: StatusFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'pending', label: 'Pending' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'done', label: 'Done' },
  { key: 'failed', label: 'Failed' },
];

const ALERT_FILTERS = new Set<StatusFilter>(['blocked', 'failed']);

function matchesFilter(task: TaskSummary, filter: StatusFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'running') return task.status === 'in_progress';
  if (filter === 'pending') return task.status === 'open' || task.status === 'ready';
  if (filter === 'blocked') return task.status === 'blocked';
  if (filter === 'done') return task.status === 'closed';
  if (filter === 'failed') return task.status === 'failed';
  return true;
}

const PAGE_SIZE = 25;

export function TasksPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [filter, setFilter] = useState<StatusFilter>('running');
  const [searchQuery, setSearchQuery] = useState('');
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [stoppingIds, setStoppingIds] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);

  const { data: polledTasks, isLoading, error } = useTasks();
  const { tasks, setTasks, updateFromEvent } = useTasksState([]);
  const killTask = useKillTask();

  useEffect(() => {
    if (polledTasks) setTasks(polledTasks);
  }, [polledTasks, setTasks]);

  useWebSocket(updateFromEvent);

  useEffect(() => {
    setStoppingIds(prev => {
      if (prev.size === 0) return prev;
      const next = new Set([...prev].filter(id => tasks.find(t => t.id === id)?.status === 'in_progress'));
      return next.size === prev.size ? prev : next;
    });
  }, [tasks]);

  const filtered = tasks.filter(t => {
    if (!matchesFilter(t, filter)) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        (t.id ?? '').toLowerCase().includes(q) ||
        (t.title ?? '').toLowerCase().includes(q) ||
        (t.cwd ?? '').toLowerCase().includes(q)
      );
    }
    return true;
  });

  const sortedFiltered = [...filtered].sort((a, b) => {
    const aTs = a.created_at ?? a.started_at ?? '';
    const bTs = b.created_at ?? b.started_at ?? '';
    return bTs.localeCompare(aTs);
  });

  const totalPages = Math.max(1, Math.ceil(sortedFiltered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const pageItems = sortedFiltered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  useEffect(() => { setPage(0); }, [filter, searchQuery]);

  const alertCounts: Partial<Record<StatusFilter, number>> = {
    blocked: tasks.filter(t => matchesFilter(t, 'blocked')).length,
    failed: tasks.filter(t => matchesFilter(t, 'failed')).length,
  };

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
          {FILTERS.map(({ key, label }) => {
            const hasAlert = ALERT_FILTERS.has(key) && (alertCounts[key] ?? 0) > 0;
            return (
              <button
                key={key}
                style={R.filterBtnStyle(filter === key)}
                onClick={() => setFilter(key)}
              >
                <span style={styles.filterBtnInner}>
                  {label}
                  {hasAlert && <span style={styles.alertDot} />}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div style={R.panelStyle()}>
        {!isMobile && (
          <div style={R.colHeaderStyle()}>
            <span style={styles.colStatus}>Status</span>
            <span style={styles.colId}>ID</span>
            <span style={styles.colTitle}>Title</span>
            <span style={styles.colCoder}>Coder / Model</span>
            <span style={styles.colContext}>Context</span>
            <span style={styles.colRuns}>Runs</span>
            <span style={styles.colTs}>Started</span>
            <span style={styles.colTs}>Completed</span>
            <span style={styles.colCwd}>Cwd</span>
            <span style={styles.colAction} />
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
            style={R.pageBtnStyle(safePage === 0)}
            disabled={safePage === 0}
            onClick={() => setPage(p => Math.max(0, p - 1))}
          >
            ← Prev
          </button>
          <span style={R.pageInfoStyle()}>
            {safePage + 1} / {totalPages}
          </span>
          <button
            style={R.pageBtnStyle(safePage >= totalPages - 1)}
            disabled={safePage >= totalPages - 1}
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
