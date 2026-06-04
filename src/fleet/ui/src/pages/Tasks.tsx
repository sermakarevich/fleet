import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useKillTask, useTasks } from '../hooks/useApi';
import { useTasksState } from '../hooks/useTasksState';
import { useWebSocket } from '../hooks/useWebSocket';
import type { TaskSummary } from '../types';

type StatusFilter = 'all' | 'running' | 'pending' | 'blocked' | 'done' | 'failed';

const FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'running', label: 'Running' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'pending', label: 'Pending' },
  { key: 'done', label: 'Done' },
  { key: 'failed', label: 'Failed' },
  { key: 'all', label: 'All' },
];

const ALERT_FILTERS = new Set<StatusFilter>(['blocked', 'failed']);

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

function formatTs(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const now = new Date();
  const pad = (n: number) => n.toString().padStart(2, '0');
  const t = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return t;
  const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()];
  return `${mo} ${d.getDate()} ${t}`;
}

function formatContext(tokens: number | null, pct: number | null): string {
  if (tokens == null) return '—';
  if (pct != null) return `${Math.round(pct)}%`;
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens);
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
  const coderModelStr = [task.coder, task.model].filter(Boolean).join(' · ');

  return (
    <div style={styles.row} onClick={() => onRowClick(task.id)}>
      <span style={{ ...styles.chip, background: chip.bg, color: chip.color }}>
        {chip.label}
      </span>
      <span style={styles.idCell}>{task.id}</span>
      <span style={styles.titleCell}>
        <span style={styles.titleText} title={task.title}>{task.title}</span>
        {task.description && (
          <span style={styles.descText} title={task.description}>{task.description}</span>
        )}
      </span>
      <span style={styles.coderCell}>
        {coderModelStr
          ? coderModelStr
          : <span style={styles.dim}>(default)</span>}
      </span>
      <span style={styles.contextCell}>{formatContext(task.context_tokens, task.context_pct)}</span>
      <span style={styles.tsCell}>{formatTs(task.started_at)}</span>
      <span style={styles.tsCell}>{formatTs(task.ended_at)}</span>
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

const PAGE_SIZE = 25;

export function Tasks() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<StatusFilter>('running');
  const [searchQuery, setSearchQuery] = useState('');
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [page, setPage] = useState(0);

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
        <h1 style={styles.heading}>tasks <span style={styles.count}>({sortedFiltered.length})</span></h1>
        <input
          type="search"
          style={styles.searchInput}
          placeholder="Search…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
        <div style={styles.filterRow}>
          {FILTERS.map(({ key, label }) => {
            const hasAlert = ALERT_FILTERS.has(key) && (alertCounts[key] ?? 0) > 0;
            return (
              <button
                key={key}
                style={{ ...styles.filterBtn, ...(filter === key ? styles.filterBtnActive : {}) }}
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

      <div style={styles.panel}>
        <div style={styles.colHeader}>
          <span style={styles.colStatus}>Status</span>
          <span style={styles.colId}>ID</span>
          <span style={styles.colTitle}>Title</span>
          <span style={styles.colCoder}>Coder / Model</span>
          <span style={styles.colContext}>Context</span>
          <span style={styles.colTs}>Started</span>
          <span style={styles.colTs}>Completed</span>
          <span style={styles.colCwd}>Cwd</span>
          <span style={styles.colAction} />
        </div>

        {sortedFiltered.length === 0 ? (
          <p style={styles.empty}>No tasks match this filter.</p>
        ) : (
          pageItems.map(task => (
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

      {totalPages > 1 && (
        <div style={styles.pagination}>
          <button
            style={{ ...styles.pageBtn, ...(safePage === 0 ? styles.pageBtnDisabled : {}) }}
            disabled={safePage === 0}
            onClick={() => setPage(p => Math.max(0, p - 1))}
          >
            ← Prev
          </button>
          <span style={styles.pageInfo}>
            {safePage + 1} / {totalPages}
          </span>
          <button
            style={{ ...styles.pageBtn, ...(safePage >= totalPages - 1 ? styles.pageBtnDisabled : {}) }}
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
  filterBtnInner: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.3rem',
  } as React.CSSProperties,
  alertDot: {
    display: 'inline-block',
    width: 7,
    height: 7,
    borderRadius: '50%',
    background: '#ef4444',
    flexShrink: 0,
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
  colCoder:   { width: '9rem', flexShrink: 0 } as React.CSSProperties,
  colContext: { width: '5rem', flexShrink: 0 } as React.CSSProperties,
  colTs:      { width: '8.5rem', flexShrink: 0 } as React.CSSProperties,
  colCwd:     { width: '7rem', flexShrink: 0 } as React.CSSProperties,
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
    boxSizing: 'border-box',
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
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.1rem',
    overflow: 'hidden',
  } as React.CSSProperties,
  titleText: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  descText: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    fontSize: '0.75rem',
    color: '#52525b',
  } as React.CSSProperties,
  coderCell: {
    width: '9rem',
    flexShrink: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  contextCell: {
    width: '5rem',
    flexShrink: 0,
    color: '#a1a1aa',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  tsCell: {
    width: '8.5rem',
    flexShrink: 0,
    color: '#a1a1aa',
    fontSize: '0.8125rem',
    fontFamily: 'monospace',
  } as React.CSSProperties,
  cwdCell: {
    width: '7rem',
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
  pagination: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.75rem',
    padding: '0.625rem 0',
    marginTop: '0.5rem',
  } as React.CSSProperties,
  pageBtn: {
    padding: '0.2rem 0.75rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  pageBtnDisabled: {
    opacity: 0.35,
    cursor: 'default',
  } as React.CSSProperties,
  pageInfo: {
    fontSize: '0.8125rem',
    color: '#71717a',
    minWidth: '4rem',
    textAlign: 'center' as const,
  } as React.CSSProperties,
};
