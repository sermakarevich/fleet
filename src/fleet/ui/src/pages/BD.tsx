import { useEffect, useMemo, useState } from 'react';
import {
  useBead,
  useBeads,
  useRemoveBeadAssignee,
  useSetBeadStatus,
  useUnblockBead,
} from '../hooks/useApi';
import { useIsMobile } from '../hooks/useIsMobile';
import type { Bead } from '../types';
import * as T from '../styles/tokens';

// ---------------------------------------------------------------------------
// The BD tab is a direct portal into the beads DB (distinct from the Tasks tab,
// which shows fleet-run tasks + their artifacts). Here you can browse every
// bead, read its full description, see why it is blocked, inspect dependencies
// and comments, change its status, unblock it, and remove its assignee.
// ---------------------------------------------------------------------------

type StatusFilter = 'all' | 'open' | 'in_progress' | 'blocked' | 'deferred' | 'closed';

const BD_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'open', label: 'Open' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'deferred', label: 'Deferred' },
  { key: 'closed', label: 'Closed' },
];

// Statuses the user can assign from the drawer (mirrors backend VALID_STATUSES,
// minus the rarely-used pinned/hooked which fleet does not surface).
const STATUS_OPTIONS = ['open', 'in_progress', 'blocked', 'deferred', 'closed'];

interface ChipStyle { label: string; color: string; bg: string }

function statusChip(status: string): ChipStyle {
  switch (status) {
    case 'in_progress': return { label: 'In progress', color: '#fff', bg: '#16a34a' };
    case 'blocked':     return { label: 'Blocked',     color: '#fff', bg: '#d97706' };
    case 'open':        return { label: 'Open',        color: '#fff', bg: '#2563eb' };
    case 'deferred':    return { label: 'Deferred',    color: '#fff', bg: '#6b7280' };
    case 'closed':      return { label: 'Closed',      color: '#a1a1aa', bg: '#27272a' };
    default:            return { label: status || '?', color: '#a1a1aa', bg: '#3f3f46' };
  }
}

// ---------------------------------------------------------------------------
// Bead row
// ---------------------------------------------------------------------------

function BeadRow({ bead, selected, onSelect }: { bead: Bead; selected: boolean; onSelect: (id: string) => void }) {
  const chip = statusChip(bead.status);
  const depCount = bead.dependency_count ?? 0;
  return (
    <div
      style={{ ...styles.row, ...(selected ? styles.rowSelected : {}) }}
      className="row-interactive"
      tabIndex={0}
      onClick={() => onSelect(bead.id)}
    >
      <span style={{ ...styles.chip, background: chip.bg, color: chip.color }}>{chip.label}</span>
      <span style={styles.idCell}>{bead.id}</span>
      <span style={styles.titleCell} title={bead.title}>{bead.title}</span>
      <span style={styles.prioCell}>
        {bead.priority != null ? bead.priority : <span style={styles.dim}>—</span>}
      </span>
      <span style={styles.assigneeCell} title={bead.assignee ?? undefined}>
        {bead.assignee ?? <span style={styles.dim}>—</span>}
      </span>
      <span style={styles.depsCell}>
        {depCount > 0 ? `${depCount} dep${depCount === 1 ? '' : 's'}` : <span style={styles.dim}>—</span>}
      </span>
    </div>
  );
}

function BeadCard({ bead, selected, onSelect }: { bead: Bead; selected: boolean; onSelect: (id: string) => void }) {
  const chip = statusChip(bead.status);
  const depCount = bead.dependency_count ?? 0;
  return (
    <div
      style={{ ...cardStyles.card, ...(selected ? { background: T.colors.borderSubtle } : {}) }}
      className="row-interactive"
      tabIndex={0}
      onClick={() => onSelect(bead.id)}
    >
      <div style={cardStyles.cardHead}>
        <span style={{ ...styles.chip, background: chip.bg, color: chip.color }}>{chip.label}</span>
        <span style={cardStyles.cardId}>{bead.id}</span>
        {bead.assignee && <span style={cardStyles.cardAssignee}>{bead.assignee}</span>}
      </div>
      <div style={cardStyles.cardTitle} title={bead.title}>{bead.title}</div>
      <div style={cardStyles.cardMeta}>
        {bead.priority != null && <span style={cardStyles.cardMetaText}>pri {bead.priority}</span>}
        {depCount > 0 && <span style={cardStyles.cardMetaText}>{depCount} dep{depCount === 1 ? '' : 's'}</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bead detail drawer
// ---------------------------------------------------------------------------

function BeadDrawer({ beadId, onClose }: { beadId: string; onClose: () => void }) {
  const { data: bead, isLoading, error } = useBead(beadId);
  const setStatus = useSetBeadStatus();
  const unblock = useUnblockBead();
  const removeAssignee = useRemoveBeadAssignee();
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null);

  const incompleteDeps = (bead?.dependencies ?? []).filter(d => d.status !== 'closed');
  const busy = setStatus.isPending || unblock.isPending || removeAssignee.isPending;

  function showFeedback(msg: string, ok: boolean) {
    setFeedback({ msg, ok });
    setTimeout(() => setFeedback(null), 2500);
  }

  return (
    <div style={styles.drawerOverlay} onClick={onClose}>
      <aside style={styles.drawer} onClick={e => e.stopPropagation()}>
        <div style={styles.drawerHeader}>
          <span style={styles.drawerId}>{beadId}</span>
          <button style={styles.closeDrawerBtn} onClick={onClose} title="Close">✕</button>
        </div>

        {isLoading && <p style={styles.msg}>Loading…</p>}
        {error && <p style={{ ...styles.msg, color: '#ef4444' }}>Error: {String(error)}</p>}

        {bead && (
          <div style={styles.drawerBody}>
            <h2 style={styles.drawerTitle}>{bead.title}</h2>

            <div style={styles.metaRow}>
              <span style={{ ...styles.chip, background: statusChip(bead.status).bg, color: statusChip(bead.status).color }}>
                {statusChip(bead.status).label}
              </span>
              {bead.priority != null && <span style={styles.metaPill}>priority {bead.priority}</span>}
              {bead.issue_type && <span style={styles.metaPill}>{bead.issue_type}</span>}
              <span style={styles.metaPill}>assignee: {bead.assignee ?? '—'}</span>
            </div>

            {/* Manage controls */}
            <div style={styles.controls}>
              <label style={styles.controlLabel}>
                Status
                <select
                  style={styles.select}
                  value={bead.status}
                  disabled={busy}
                  onChange={e => setStatus.mutate(
                    { id: beadId, status: e.target.value },
                    {
                      onSuccess: () => showFeedback('Saved', true),
                      onError: (err) => showFeedback(`Error: ${String(err)}`, false),
                    }
                  )}
                >
                  {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                  {!STATUS_OPTIONS.includes(bead.status) && (
                    <option value={bead.status}>{bead.status}</option>
                  )}
                </select>
              </label>
              {bead.status === 'blocked' && (
                <button style={styles.unblockBtn} disabled={busy} onClick={() => unblock.mutate(beadId)}>
                  Unblock
                </button>
              )}
              {bead.assignee && (
                <button
                  style={styles.unassignBtn}
                  disabled={busy}
                  onClick={() => {
                    if (!window.confirm(`Remove assignee "${bead.assignee}" from ${beadId}?`)) return;
                    removeAssignee.mutate(beadId, {
                      onSuccess: () => showFeedback('Assignee removed', true),
                      onError: (err) => showFeedback(`Error: ${String(err)}`, false),
                    });
                  }}
                >
                  Remove assignee
                </button>
              )}
            </div>
            {feedback && (
              <p style={{ ...styles.feedbackMsg, color: feedback.ok ? '#4ade80' : '#f87171' }}>
                {feedback.msg}
              </p>
            )}

            {/* Why blocked */}
            {bead.status === 'blocked' && (
              <section style={styles.section}>
                <h3 style={styles.sectionTitle}>Why blocked</h3>
                {bead.notes && <pre style={styles.notes}>{bead.notes}</pre>}
                {incompleteDeps.length > 0 && (
                  <div style={styles.blockedDeps}>
                    <span style={styles.dim}>
                      Waiting on {incompleteDeps.length} open dependenc{incompleteDeps.length === 1 ? 'y' : 'ies'}:
                    </span>
                    {incompleteDeps.map(d => (
                      <div key={d.id} style={styles.depItem}>
                        <span style={styles.depId}>{d.id}</span>
                        <span style={styles.depTitle} title={d.title ?? undefined}>{d.title ?? ''}</span>
                        <span style={{ ...styles.depStatusChip, background: statusChip(d.status ?? '').bg, color: statusChip(d.status ?? '').color }}>
                          {d.status ?? '?'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {!bead.notes && incompleteDeps.length === 0 && (
                  <p style={styles.dim}>No recorded reason — blocked manually. Use Unblock to reopen.</p>
                )}
              </section>
            )}

            {/* Description */}
            <section style={styles.section}>
              <h3 style={styles.sectionTitle}>Description</h3>
              {bead.description
                ? <pre style={styles.desc}>{bead.description}</pre>
                : <p style={styles.dim}>No description.</p>}
            </section>

            {/* Dependencies */}
            <section style={styles.section}>
              <h3 style={styles.sectionTitle}>Dependencies ({bead.dependencies.length})</h3>
              {bead.dependencies.length === 0
                ? <p style={styles.dim}>None.</p>
                : bead.dependencies.map(d => (
                    <div key={d.id} style={styles.depItem}>
                      <span style={styles.depId}>{d.id}</span>
                      <span style={styles.depTitle} title={d.title ?? undefined}>{d.title ?? ''}</span>
                      <span style={{ ...styles.depStatusChip, background: statusChip(d.status ?? '').bg, color: statusChip(d.status ?? '').color }}>
                        {d.status ?? '?'}
                      </span>
                      {d.dependency_type && <span style={styles.depType}>{d.dependency_type}</span>}
                    </div>
                  ))}
            </section>

            {/* Comments */}
            <section style={styles.section}>
              <h3 style={styles.sectionTitle}>Comments ({bead.comments.length})</h3>
              {bead.comments.length === 0
                ? <p style={styles.dim}>None.</p>
                : bead.comments.map((c, i) => (
                    <div key={c.id ?? i} style={styles.comment}>
                      <div style={styles.commentMeta}>
                        <span style={styles.commentAuthor}>{c.author ?? 'unknown'}</span>
                        {c.created_at && <span style={styles.dim}>{c.created_at}</span>}
                      </div>
                      <div style={styles.commentText}>{c.text}</div>
                    </div>
                  ))}
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

const PAGE_SIZE = 25;

// ---------------------------------------------------------------------------
// BD page
// ---------------------------------------------------------------------------

export function BD() {
  const { data: beads, isLoading, error } = useBeads();
  const isMobile = useIsMobile();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('in_progress');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    if (!beads) return [];
    let visible = beads.filter(b => statusFilter === 'all' || b.status === statusFilter);
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      visible = visible.filter(b =>
        b.id.toLowerCase().includes(q) ||
        b.title.toLowerCase().includes(q) ||
        (b.assignee ?? '').toLowerCase().includes(q)
      );
    }
    return [...visible].sort((a, b) => {
      const aTs = a.created_at ?? '';
      const bTs = b.created_at ?? '';
      return bTs.localeCompare(aTs) || a.id.localeCompare(b.id);
    });
  }, [beads, statusFilter, searchQuery]);

  useEffect(() => { setPage(0); }, [statusFilter, searchQuery]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const pageItems = sorted.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  if (isLoading) {
    return <p style={styles.msg}>Loading…</p>;
  }
  if (error) {
    return <p style={{ ...styles.msg, color: '#ef4444' }}>Error: {String(error)}</p>;
  }

  return (
    <div style={{ ...styles.page, padding: isMobile ? '0.75rem' : '1rem 1.5rem' }}>
      <div style={styles.topBar}>
        <h1 style={styles.heading}>
          beads <span style={styles.count}>({sorted.length})</span>
        </h1>
        <input
          type="search"
          style={{ ...styles.searchInput, width: isMobile ? '100%' : '15rem' }}
          placeholder="Search id, title, assignee…"
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
        {!isMobile && (
          <div style={styles.colHeader}>
            <span style={styles.cStatus}>Status</span>
            <span style={styles.cId}>ID</span>
            <span style={styles.cTitle}>Title</span>
            <span style={styles.cPrio}>Pri</span>
            <span style={styles.cAssignee}>Assignee</span>
            <span style={styles.cDeps}>Deps</span>
          </div>
        )}
        {sorted.length === 0 ? (
          <p style={styles.empty}>No beads.</p>
        ) : (
          pageItems.map(bead => isMobile ? (
            <BeadCard
              key={bead.id}
              bead={bead}
              selected={selectedId === bead.id}
              onSelect={setSelectedId}
            />
          ) : (
            <BeadRow
              key={bead.id}
              bead={bead}
              selected={selectedId === bead.id}
              onSelect={setSelectedId}
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

      {selectedId && <BeadDrawer beadId={selectedId} onClose={() => setSelectedId(null)} />}
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
    width: '15rem',
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
  cStatus:   { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  cId:       { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  cTitle:    { flex: 1, minWidth: 0 } as React.CSSProperties,
  cPrio:     { width: '3rem', flexShrink: 0 } as React.CSSProperties,
  cAssignee: { width: '8rem', flexShrink: 0 } as React.CSSProperties,
  cDeps:     { width: '5rem', flexShrink: 0 } as React.CSSProperties,
  row: {
    display: 'flex',
    alignItems: 'center',
    padding: '0.5rem 1rem',
    gap: '0.75rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer',
    fontSize: '0.875rem',
    color: '#d4d4d8',
  } as React.CSSProperties,
  rowSelected: {
    background: T.colors.borderSubtle,
  } as React.CSSProperties,
  chip: {
    ...T.badge,
    width: '6rem',
    flexShrink: 0,
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
    color: T.colors.textSecondary,
    textAlign: 'center' as const,
  } as React.CSSProperties,
  assigneeCell: {
    width: '8rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  depsCell: {
    width: '5rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
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

  // Drawer
  drawerOverlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.45)',
    display: 'flex',
    justifyContent: 'flex-end',
    zIndex: 900,
  } as React.CSSProperties,
  drawer: {
    width: 'min(34rem, 100%)',
    height: '100%',
    background: T.colors.bgSurface,
    borderLeft: `1px solid ${T.colors.border}`,
    display: 'flex',
    flexDirection: 'column' as const,
    boxShadow: '-8px 0 24px rgba(0,0,0,0.4)',
  } as React.CSSProperties,
  drawerHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0.625rem 1rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    flexShrink: 0,
  } as React.CSSProperties,
  drawerId: {
    fontFamily: 'monospace',
    color: '#60a5fa',
    fontSize: '0.875rem',
    fontWeight: 600,
  } as React.CSSProperties,
  closeDrawerBtn: {
    background: 'transparent',
    border: 'none',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '1rem',
    lineHeight: 1,
    padding: '0.25rem',
  } as React.CSSProperties,
  drawerBody: {
    padding: '1rem',
    overflowY: 'auto' as const,
    flex: 1,
  } as React.CSSProperties,
  drawerTitle: {
    margin: '0 0 0.75rem',
    fontSize: '1rem',
    fontWeight: 600,
    color: '#f4f4f5',
    lineHeight: 1.4,
  } as React.CSSProperties,
  metaRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    flexWrap: 'wrap' as const,
    marginBottom: '0.875rem',
  } as React.CSSProperties,
  metaPill: {
    padding: '0.15rem 0.5rem',
    background: T.colors.borderSubtle,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textSecondary,
    fontSize: '0.75rem',
  } as React.CSSProperties,
  controls: {
    display: 'flex',
    alignItems: 'flex-end',
    gap: '0.625rem',
    flexWrap: 'wrap' as const,
    padding: '0.75rem',
    background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 6,
    marginBottom: '1rem',
  } as React.CSSProperties,
  controlLabel: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.25rem',
    fontSize: '0.7rem',
    color: T.colors.textDim,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  } as React.CSSProperties,
  select: {
    padding: '0.25rem 0.5rem',
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textPrimary,
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
    cursor: 'pointer',
  } as React.CSSProperties,
  unblockBtn: {
    padding: '0.3rem 0.75rem',
    background: 'transparent',
    border: '1px solid #2563eb',
    borderRadius: 4,
    color: '#60a5fa',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  unassignBtn: {
    padding: '0.3rem 0.75rem',
    background: 'transparent',
    border: '1px solid #78716c',
    borderRadius: 4,
    color: '#a8a29e',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  feedbackMsg: {
    margin: '0 0 0.75rem',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  section: {
    marginBottom: '1.25rem',
  } as React.CSSProperties,
  sectionTitle: {
    margin: '0 0 0.5rem',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: T.colors.textDim,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  } as React.CSSProperties,
  notes: {
    margin: '0 0 0.5rem',
    padding: '0.625rem 0.75rem',
    background: '#2a1d05',
    border: '1px solid #78491a',
    borderRadius: 6,
    color: '#fcd9a0',
    fontSize: '0.8125rem',
    fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
  } as React.CSSProperties,
  blockedDeps: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.375rem',
  } as React.CSSProperties,
  desc: {
    margin: 0,
    padding: '0.625rem 0.75rem',
    background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 6,
    color: '#d4d4d8',
    fontSize: '0.8125rem',
    fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
    lineHeight: 1.5,
  } as React.CSSProperties,
  depItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    padding: '0.375rem 0.5rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  depId: {
    fontFamily: 'monospace',
    color: '#60a5fa',
    flexShrink: 0,
  } as React.CSSProperties,
  depTitle: {
    flex: 1,
    minWidth: 0,
    color: '#d4d4d8',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  depStatusChip: {
    flexShrink: 0,
    padding: '0.05rem 0.4rem',
    borderRadius: 4,
    fontSize: '0.7rem',
    fontWeight: 600,
  } as React.CSSProperties,
  depType: {
    flexShrink: 0,
    color: T.colors.textMuted,
    fontSize: '0.7rem',
    fontFamily: 'monospace',
  } as React.CSSProperties,
  comment: {
    padding: '0.5rem 0',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  commentMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginBottom: '0.25rem',
    fontSize: '0.75rem',
  } as React.CSSProperties,
  commentAuthor: {
    color: T.colors.textSecondary,
    fontWeight: 600,
  } as React.CSSProperties,
  commentText: {
    color: '#d4d4d8',
    fontSize: '0.8125rem',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
    lineHeight: 1.5,
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
  cardAssignee: {
    fontSize: '0.75rem',
    color: T.colors.textSecondary,
    flexShrink: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    maxWidth: '7rem',
  } as React.CSSProperties,
  cardTitle: {
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
