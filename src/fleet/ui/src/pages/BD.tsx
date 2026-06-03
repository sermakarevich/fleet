import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCloseTask, useDeleteTask, useRemoveAssignee, useRequeueTask, useTasks } from '../hooks/useApi';
import type { TaskSummary } from '../types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type StatusFilter = 'all' | 'running' | 'pending' | 'blocked' | 'done' | 'failed';

const BD_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'pending', label: 'Pending' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'done', label: 'Done' },
  { key: 'failed', label: 'Failed' },
];

function matchesStatusFilter(task: TaskSummary, filter: StatusFilter): boolean {
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

const STATUS_ORDER: Record<string, number> = {
  open: 0, ready: 0,
  in_progress: 1,
  blocked: 2,
  closed: 3, failed: 3,
};

function taskOrder(t: TaskSummary): number {
  return STATUS_ORDER[t.status] ?? 9;
}

// ---------------------------------------------------------------------------
// BD task row
// ---------------------------------------------------------------------------

interface RowProps {
  task: TaskSummary;
  onOpen: (id: string) => void;
  onClose: (id: string) => void;
  onRemove: (id: string) => void;
  onUnassign: (id: string) => void;
  onView: (id: string) => void;
}

function BDRow({ task, onOpen, onClose, onRemove, onUnassign, onView }: RowProps) {
  const chip = statusChip(task.status);
  const isOpenable = task.status !== 'open' && task.status !== 'ready';
  const isCloseable = task.status !== 'closed';

  return (
    <div style={styles.row} onClick={() => onView(task.id)}>
      <span style={{ ...styles.chip, background: chip.bg, color: chip.color }}>
        {chip.label}
      </span>
      <span style={styles.idCell}>{task.id}</span>
      <span style={styles.titleCell} title={task.title}>{task.title}</span>
      <span style={styles.prioCell}>
        {task.priority != null ? task.priority : <span style={styles.dim}>—</span>}
      </span>
      <span style={styles.coderCell}>
        {task.coder ?? <span style={styles.dim}>(default)</span>}
      </span>
      <span style={styles.depsCell} onClick={e => e.stopPropagation()}>
        {task.depends_on.length > 0
          ? task.depends_on.map(dep => (
              <span key={dep} style={styles.depBadge}>{dep}</span>
            ))
          : <span style={styles.dim}>—</span>}
      </span>
      <span style={styles.actionCell} onClick={e => e.stopPropagation()}>
        <button style={styles.viewBtn} onClick={() => onView(task.id)}>View</button>
        {task.coder && (
          <button style={styles.unassignBtn} onClick={() => onUnassign(task.id)}>Unassign</button>
        )}
        {isOpenable && (
          <button style={styles.openBtn} onClick={() => onOpen(task.id)}>Open</button>
        )}
        {isCloseable && (
          <button style={styles.closeRowBtn} onClick={() => onClose(task.id)}>Close</button>
        )}
        <button style={styles.removeBtn} onClick={() => onRemove(task.id)}>Remove</button>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BD page
// ---------------------------------------------------------------------------

export function BD() {
  const navigate = useNavigate();
  const { data: tasksData, isLoading, error } = useTasks();
  const requeueTask = useRequeueTask();
  const closeTask = useCloseTask();
  const deleteTask = useDeleteTask();
  const removeAssignee = useRemoveAssignee();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const sorted = useMemo(() => {
    if (!tasksData) return [];
    let visible = tasksData.filter(t => matchesStatusFilter(t, statusFilter));
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      visible = visible.filter(t =>
        t.id.toLowerCase().includes(q) ||
        t.title.toLowerCase().includes(q) ||
        (t.cwd ?? '').toLowerCase().includes(q)
      );
    }
    return [...visible].sort((a, b) => taskOrder(a) - taskOrder(b));
  }, [tasksData, statusFilter, searchQuery]);

  if (isLoading) {
    return <p style={styles.msg}>Loading…</p>;
  }
  if (error) {
    return <p style={{ ...styles.msg, color: '#ef4444' }}>Error: {String(error)}</p>;
  }

  return (
    <div style={styles.page}>
      <div style={styles.topBar}>
        <h1 style={styles.heading}>
          BD Queue <span style={styles.count}>({sorted.length})</span>
        </h1>
        <input
          type="search"
          style={styles.searchInput}
          placeholder="Search…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
        <div style={styles.filterRow}>
          {BD_FILTERS.map(({ key, label }) => (
            <button
              key={key}
              style={{ ...styles.filterBtn, ...(statusFilter === key ? styles.filterBtnActive : {}) }}
              onClick={() => setStatusFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div style={styles.panel}>
        <div style={styles.colHeader}>
          <span style={styles.cStatus}>Status</span>
          <span style={styles.cId}>ID</span>
          <span style={styles.cTitle}>Title</span>
          <span style={styles.cPrio}>Pri</span>
          <span style={styles.cCoder}>Coder</span>
          <span style={styles.cDeps}>Depends on</span>
          <span style={styles.cAction} />
        </div>
        {sorted.length === 0 ? (
          <p style={styles.empty}>No tasks in queue.</p>
        ) : (
          sorted.map(task => (
            <BDRow
              key={task.id}
              task={task}
              onOpen={id => { void requeueTask.mutateAsync(id); }}
              onClose={id => { void closeTask.mutateAsync(id); }}
              onRemove={id => { void deleteTask.mutateAsync(id); }}
              onUnassign={id => { void removeAssignee.mutateAsync(id); }}
              onView={id => navigate(`/tasks/${id}`)}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

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
  cStatus: { width: '5rem', flexShrink: 0 } as React.CSSProperties,
  cId:     { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  cTitle:  { flex: 1, minWidth: 0 } as React.CSSProperties,
  cPrio:   { width: '3rem', flexShrink: 0 } as React.CSSProperties,
  cCoder:  { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  cDeps:   { width: '10rem', flexShrink: 0 } as React.CSSProperties,
  cAction: { width: '15rem', flexShrink: 0 } as React.CSSProperties,
  row: {
    display: 'flex',
    alignItems: 'center',
    padding: '0.5rem 1rem',
    gap: '0.75rem',
    borderBottom: '1px solid #27272a',
    cursor: 'pointer',
    fontSize: '0.875rem',
    color: '#d4d4d8',
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
  prioCell: {
    width: '3rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    color: '#a1a1aa',
    textAlign: 'center' as const,
  } as React.CSSProperties,
  coderCell: {
    width: '6rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  depsCell: {
    width: '10rem',
    flexShrink: 0,
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: '0.25rem',
    alignItems: 'center',
  } as React.CSSProperties,
  depBadge: {
    display: 'inline-block',
    padding: '0.1rem 0.4rem',
    background: '#27272a',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#a1a1aa',
    fontSize: '0.7rem',
    fontFamily: 'monospace',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  actionCell: {
    width: '15rem',
    flexShrink: 0,
    display: 'flex',
    gap: '0.3rem',
    alignItems: 'center',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  viewBtn: {
    padding: '0.15rem 0.4rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#71717a',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  unassignBtn: {
    padding: '0.15rem 0.4rem',
    background: 'transparent',
    border: '1px solid #78716c',
    borderRadius: 4,
    color: '#a8a29e',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  openBtn: {
    padding: '0.15rem 0.4rem',
    background: 'transparent',
    border: '1px solid #2563eb',
    borderRadius: 4,
    color: '#60a5fa',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  closeRowBtn: {
    padding: '0.15rem 0.4rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#71717a',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  removeBtn: {
    padding: '0.15rem 0.4rem',
    background: 'transparent',
    border: '1px solid #7f1d1d',
    borderRadius: 4,
    color: '#f87171',
    cursor: 'pointer',
    fontSize: '0.75rem',
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
