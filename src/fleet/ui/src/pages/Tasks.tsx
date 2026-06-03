import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useKillTask, useTasks } from '../hooks/useApi';
import { useTasksState } from '../hooks/useTasksState';
import { useWebSocket } from '../hooks/useWebSocket';
import type { TaskSummary } from '../types';

type StatusFilter = 'all' | 'running' | 'pending' | 'blocked' | 'done' | 'failed';

const FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'pending', label: 'Pending' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'done', label: 'Done' },
  { key: 'failed', label: 'Failed' },
];

const KILL_ELIGIBLE = new Set(['in_progress', 'blocked', 'open', 'ready']);

function matchesFilter(task: TaskSummary, filter: StatusFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'running') return task.status === 'in_progress';
  if (filter === 'pending') return task.status === 'open' || task.status === 'ready';
  if (filter === 'blocked') return task.status === 'blocked';
  if (filter === 'done') return task.status === 'closed';
  if (filter === 'failed') return task.status === 'failed';
  return true;
}

interface ChipStyle { label: string; color: string; bg: string }

function statusChip(status: string): ChipStyle {
  switch (status) {
    case 'in_progress': return { label: 'Running', color: '#fff', bg: '#16a34a' };
    case 'blocked':     return { label: 'Blocked', color: '#fff', bg: '#d97706' };
    case 'open':
    case 'ready':       return { label: 'Pending', color: '#fff', bg: '#2563eb' };
    case 'closed':      return { label: 'Done',    color: '#71717a', bg: '#27272a' };
    case 'failed':      return { label: 'Failed',  color: '#fff', bg: '#dc2626' };
    default:            return { label: status,    color: '#a1a1aa', bg: '#3f3f46' };
  }
}

function formatElapsed(sec: number | null): string {
  if (sec == null) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

interface RowProps {
  task: TaskSummary;
  confirmingId: string | null;
  onKillClick: (id: string) => void;
  onKillConfirm: (id: string) => void;
  onKillCancel: () => void;
  onRowClick: (id: string) => void;
}

function TaskRow({ task, confirmingId, onKillClick, onKillConfirm, onKillCancel, onRowClick }: RowProps) {
  const chip = statusChip(task.status);
  const cwdShort = task.cwd ? (task.cwd.split('/').pop() ?? task.cwd) : '—';
  const isConfirming = confirmingId === task.id;
  const killEligible = KILL_ELIGIBLE.has(task.status);

  return (
    <div style={styles.row} onClick={() => onRowClick(task.id)}>
      <span style={{ ...styles.chip, background: chip.bg, color: chip.color }}>
        {chip.label}
      </span>
      <span style={styles.idCell}>{task.id}</span>
      <span style={styles.titleCell} title={task.title}>{task.title}</span>
      <span style={styles.coderCell}>
        {task.coder
          ? task.coder
          : <span style={styles.dim}>(default)</span>}
      </span>
      <span style={styles.elapsedCell}>{formatElapsed(task.elapsed_sec)}</span>
      <span style={styles.cwdCell} title={task.cwd ?? undefined}>{cwdShort}</span>
      <span style={styles.actionCell} onClick={e => e.stopPropagation()}>
        {killEligible && !isConfirming && (
          <button style={styles.killBtn} onClick={() => onKillClick(task.id)}>
            Kill
          </button>
        )}
        {isConfirming && (
          <span style={styles.confirm}>
            <span style={styles.confirmLabel}>Confirm kill?</span>
            <button style={styles.yesBtn} onClick={() => onKillConfirm(task.id)}>Yes</button>
            <button style={styles.cancelBtn} onClick={onKillCancel}>Cancel</button>
          </span>
        )}
      </span>
    </div>
  );
}

export function Tasks() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const { data: polledTasks, isLoading, error } = useTasks();
  const { tasks, setTasks, updateFromEvent } = useTasksState([]);
  const killTask = useKillTask();

  useEffect(() => {
    if (polledTasks) setTasks(polledTasks);
  }, [polledTasks, setTasks]);

  useWebSocket(updateFromEvent);

  const filtered = tasks.filter(t => {
    if (!matchesFilter(t, filter)) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        t.id.toLowerCase().includes(q) ||
        t.title.toLowerCase().includes(q) ||
        (t.cwd ?? '').toLowerCase().includes(q)
      );
    }
    return true;
  });

  const handleKillConfirm = (id: string) => {
    void killTask.mutateAsync(id).finally(() => setConfirmingId(null));
  };

  if (isLoading && tasks.length === 0) {
    return <p style={styles.msg}>Loading…</p>;
  }
  if (error && tasks.length === 0) {
    return <p style={{ ...styles.msg, color: '#ef4444' }}>Error: {String(error)}</p>;
  }

  return (
    <div style={styles.page}>
      <div style={styles.topBar}>
        <h1 style={styles.heading}>Tasks <span style={styles.count}>({tasks.length})</span></h1>
        <input
          type="search"
          style={styles.searchInput}
          placeholder="Search…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
        <div style={styles.filterRow}>
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              style={{ ...styles.filterBtn, ...(filter === key ? styles.filterBtnActive : {}) }}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div style={styles.panel}>
        <div style={styles.colHeader}>
          <span style={styles.colStatus}>Status</span>
          <span style={styles.colId}>ID</span>
          <span style={styles.colTitle}>Title</span>
          <span style={styles.colCoder}>Coder</span>
          <span style={styles.colElapsed}>Elapsed</span>
          <span style={styles.colCwd}>Cwd</span>
          <span style={styles.colAction} />
        </div>

        {filtered.length === 0 ? (
          <p style={styles.empty}>No tasks match this filter.</p>
        ) : (
          filtered.map(task => (
            <TaskRow
              key={task.id}
              task={task}
              confirmingId={confirmingId}
              onKillClick={id => setConfirmingId(id)}
              onKillConfirm={handleKillConfirm}
              onKillCancel={() => setConfirmingId(null)}
              onRowClick={id => navigate(`/tasks/${id}`)}
            />
          ))
        )}
      </div>
    </div>
  );
}

const styles = {
  page: {
    padding: '1rem 1.5rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  msg: {
    padding: '1rem',
    color: '#71717a',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
    marginBottom: '0.875rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  heading: {
    margin: 0,
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  count: {
    fontWeight: 400,
    color: '#71717a',
    fontSize: '0.875rem',
  } as React.CSSProperties,
  searchInput: {
    padding: '0.2rem 0.625rem',
    background: '#09090b',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#e4e4e7',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
    outline: 'none',
    width: '13rem',
  } as React.CSSProperties,
  filterRow: {
    display: 'flex',
    gap: '0.375rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  filterBtn: {
    padding: '0.2rem 0.625rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#71717a',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
    lineHeight: 1.4,
  } as React.CSSProperties,
  filterBtnActive: {
    background: '#3b82f6',
    borderColor: '#3b82f6',
    color: '#fff',
  } as React.CSSProperties,
  panel: {
    background: '#1c1c20',
    border: '1px solid #3f3f46',
    borderRadius: 8,
    overflow: 'hidden',
  } as React.CSSProperties,
  colHeader: {
    display: 'flex',
    alignItems: 'center',
    padding: '0.4rem 1rem',
    borderBottom: '1px solid #27272a',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: '#71717a',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    gap: '0.75rem',
  } as React.CSSProperties,
  colStatus:  { width: '5rem', flexShrink: 0 } as React.CSSProperties,
  colId:      { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  colTitle:   { flex: 1, minWidth: 0 } as React.CSSProperties,
  colCoder:   { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  colElapsed: { width: '5rem', flexShrink: 0 } as React.CSSProperties,
  colCwd:     { width: '8rem', flexShrink: 0 } as React.CSSProperties,
  colAction:  { width: '10rem', flexShrink: 0 } as React.CSSProperties,
  row: {
    display: 'flex',
    alignItems: 'center',
    padding: '0.5rem 1rem',
    gap: '0.75rem',
    borderBottom: '1px solid #27272a',
    cursor: 'pointer',
    fontSize: '0.875rem',
    color: '#d4d4d8',
    transition: 'background 0.1s',
  } as React.CSSProperties,
  chip: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '5rem',
    flexShrink: 0,
    padding: '0.15rem 0.5rem',
    borderRadius: 4,
    fontSize: '0.75rem',
    fontWeight: 600,
    letterSpacing: '0.01em',
  } as React.CSSProperties,
  idCell: {
    width: '6rem',
    flexShrink: 0,
    fontFamily: 'monospace',
    color: '#60a5fa',
    fontSize: '0.8125rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  titleCell: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  coderCell: {
    width: '6rem',
    flexShrink: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  elapsedCell: {
    width: '5rem',
    flexShrink: 0,
    color: '#a1a1aa',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  cwdCell: {
    width: '8rem',
    flexShrink: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    color: '#71717a',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  actionCell: {
    width: '10rem',
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
  } as React.CSSProperties,
  killBtn: {
    padding: '0.2rem 0.625rem',
    background: 'transparent',
    border: '1px solid #ef4444',
    borderRadius: 4,
    color: '#ef4444',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  confirm: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
  } as React.CSSProperties,
  confirmLabel: {
    fontSize: '0.8125rem',
    color: '#a1a1aa',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  yesBtn: {
    padding: '0.2rem 0.5rem',
    background: '#ef4444',
    border: '1px solid #ef4444',
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
    fontWeight: 600,
  } as React.CSSProperties,
  cancelBtn: {
    padding: '0.2rem 0.5rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  empty: {
    padding: '1.5rem 1rem',
    color: '#52525b',
    fontSize: '0.875rem',
    margin: 0,
    textAlign: 'center' as const,
  } as React.CSSProperties,
  dim: {
    color: '#52525b',
  } as React.CSSProperties,
};
