import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useKillTask, useTasks } from '../hooks/useApi';
import { useTasksState } from '../hooks/useTasksState';
import { useWebSocket } from '../hooks/useWebSocket';
import { useIsMobile } from '../hooks/useIsMobile';
import type { TaskSummary } from '../types';
import * as T from '../styles/tokens';

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

function statusChip(status: string, stopping = false): ChipStyle {
  if (stopping) return { label: 'Stopping…', color: '#fff', bg: '#92400e' };
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
  stoppingIds: Set<string>;
  onKillClick: (id: string) => void;
  onKillConfirm: (id: string) => void;
  onKillCancel: () => void;
  onRowClick: (id: string) => void;
}

function TaskRow({ task, confirmingId, stoppingIds, onKillClick, onKillConfirm, onKillCancel, onRowClick }: RowProps) {
  const isStopping = stoppingIds.has(task.id) && task.status === 'in_progress';
  const chip = statusChip(task.status, isStopping);
  const cwdShort = task.cwd ? (task.cwd.split('/').pop() ?? task.cwd) : '—';
  const isConfirming = confirmingId === task.id;
  const killEligible = KILL_ELIGIBLE.has(task.status);
  const coderModelStr = [task.coder, task.model].filter(Boolean).join(' · ');

  return (
    <div style={styles.row} className="row-interactive" tabIndex={0} onClick={() => onRowClick(task.id)}>
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
        {killEligible && !isConfirming && !isStopping && (
          <button style={styles.killBtn} onClick={() => onKillClick(task.id)}>
            Kill
          </button>
        )}
        {isStopping && (
          <span style={styles.stoppingLabel}>stopping…</span>
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

function TaskCard({ task, confirmingId, stoppingIds, onKillClick, onKillConfirm, onKillCancel, onRowClick }: RowProps) {
  const isStopping = stoppingIds.has(task.id) && task.status === 'in_progress';
  const chip = statusChip(task.status, isStopping);
  const cwdShort = task.cwd ? (task.cwd.split('/').pop() ?? task.cwd) : '—';
  const isConfirming = confirmingId === task.id;
  const killEligible = KILL_ELIGIBLE.has(task.status);
  const coderModelStr = [task.coder, task.model].filter(Boolean).join(' · ');

  return (
    <div
      style={cardStyles.card}
      className="row-interactive"
      tabIndex={0}
      onClick={() => onRowClick(task.id)}
    >
      <div style={cardStyles.cardHead}>
        <span style={{ ...styles.chip, ...cardStyles.chipInCard, background: chip.bg, color: chip.color }}>
          {chip.label}
        </span>
        <span style={cardStyles.cardId}>{task.id}</span>
        <span style={cardStyles.cardActions} onClick={e => e.stopPropagation()}>
          {killEligible && !isConfirming && !isStopping && (
            <button style={styles.killBtn} onClick={() => onKillClick(task.id)}>Kill</button>
          )}
          {isStopping && <span style={styles.stoppingLabel}>stopping…</span>}
          {isConfirming && (
            <span style={styles.confirm}>
              <button style={styles.yesBtn} onClick={() => onKillConfirm(task.id)}>Yes</button>
              <button style={styles.cancelBtn} onClick={onKillCancel}>No</button>
            </span>
          )}
        </span>
      </div>
      <div style={cardStyles.cardTitle}>{task.title}</div>
      {task.description && <div style={cardStyles.cardDesc}>{task.description}</div>}
      <div style={cardStyles.cardMeta}>
        <span style={cardStyles.cardMetaText}>{coderModelStr || '(default)'}</span>
        <span style={cardStyles.cardMetaText}>{formatTs(task.started_at)}</span>
        <span style={cardStyles.cardMetaText} title={task.cwd ?? undefined}>{cwdShort}</span>
      </div>
    </div>
  );
}

const PAGE_SIZE = 25;

export function Tasks() {
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
    void killTask.mutateAsync(id)
      .then(() => setStoppingIds(prev => new Set([...prev, id])))
      .finally(() => setConfirmingId(null));
  };

  if (isLoading && tasks.length === 0) {
    return <p style={styles.msg}>Loading…</p>;
  }
  if (error && tasks.length === 0) {
    return <p style={{ ...styles.msg, color: '#ef4444' }}>Error: {String(error)}</p>;
  }

  return (
    <div style={{ ...styles.page, padding: isMobile ? '0.75rem' : '1rem 1.5rem' }}>
      <div style={styles.topBar}>
        <h1 style={styles.heading}>tasks <span style={styles.count}>({sortedFiltered.length})</span></h1>
        <input
          type="search"
          style={{ ...styles.searchInput, width: isMobile ? '100%' : '13rem' }}
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
        {!isMobile && (
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
        )}

        {sortedFiltered.length === 0 ? (
          <p style={styles.empty}>No tasks match this filter.</p>
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
    color: T.colors.textDim,
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
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  count: {
    fontWeight: 400,
    color: T.colors.textDim,
    fontSize: '0.875rem',
  } as React.CSSProperties,
  searchInput: {
    padding: '0.2rem 0.625rem',
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textPrimary,
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
    ...T.btnGhost,
    padding: '0.2rem 0.625rem',
    fontSize: '0.8125rem',
    color: T.colors.textDim,
    lineHeight: 1.4,
  } as React.CSSProperties,
  filterBtnActive: {
    background: T.colors.accent,
    borderColor: T.colors.accent,
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
    background: T.colors.danger,
    flexShrink: 0,
  } as React.CSSProperties,
  panel: {
    ...T.panel,
    overflow: 'hidden',
  } as React.CSSProperties,
  colHeader: {
    display: 'flex',
    alignItems: 'center',
    padding: '0.4rem 1rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.75rem',
    fontWeight: 600,
    color: T.colors.textDim,
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
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer',
    fontSize: '0.875rem',
    color: '#d4d4d8',
    transition: 'background 0.1s',
  } as React.CSSProperties,
  chip: {
    ...T.badge,
    width: '5rem',
    flexShrink: 0,
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
    color: T.colors.textMuted,
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
    color: T.colors.textSecondary,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  tsCell: {
    width: '8.5rem',
    flexShrink: 0,
    color: T.colors.textSecondary,
    fontSize: '0.8125rem',
    fontFamily: 'monospace',
  } as React.CSSProperties,
  cwdCell: {
    width: '7rem',
    flexShrink: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    color: T.colors.textDim,
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
    ...T.btnDanger,
    padding: '0.2rem 0.625rem',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  stoppingLabel: {
    fontSize: '0.8125rem',
    color: '#fb923c',
    fontStyle: 'italic',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  confirm: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
  } as React.CSSProperties,
  confirmLabel: {
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  yesBtn: {
    padding: '0.2rem 0.5rem',
    background: T.colors.danger,
    border: `1px solid ${T.colors.danger}`,
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
    fontWeight: 600,
  } as React.CSSProperties,
  cancelBtn: {
    ...T.btnGhost,
    padding: '0.2rem 0.5rem',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  empty: {
    padding: '1.5rem 1rem',
    color: T.colors.textMuted,
    fontSize: '0.875rem',
    margin: 0,
    textAlign: 'center' as const,
  } as React.CSSProperties,
  dim: {
    color: T.colors.textMuted,
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
    ...T.btnGhost,
    padding: '0.2rem 0.75rem',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  pageBtnDisabled: {
    opacity: 0.35,
    cursor: 'default',
  } as React.CSSProperties,
  pageInfo: {
    fontSize: '0.8125rem',
    color: T.colors.textDim,
    minWidth: '4rem',
    textAlign: 'center' as const,
  } as React.CSSProperties,
};

const cardStyles = {
  card: {
    padding: '0.625rem 0.875rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.3rem',
    fontSize: '0.875rem',
    color: '#d4d4d8',
  } as React.CSSProperties,
  cardHead: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  } as React.CSSProperties,
  chipInCard: {
    flexShrink: 0,
    width: 'auto',
  } as React.CSSProperties,
  cardId: {
    fontFamily: 'monospace',
    color: '#60a5fa',
    fontSize: '0.8125rem',
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardActions: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
    flexShrink: 0,
  } as React.CSSProperties,
  cardTitle: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardDesc: {
    fontSize: '0.75rem',
    color: T.colors.textMuted,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardMeta: {
    display: 'flex',
    gap: '0.625rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  cardMetaText: {
    fontSize: '0.75rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
};
