/**
 * Manage controls for one bead: status select, unblock, remove assignee.
 * Called by BeadDrawer; every outcome toasts via ToastContext.
 */
import { useRemoveBeadAssignee, useSetBeadStatus, useUnblockBead } from '../../shared/hooks/useApi';
import type { BeadDetail } from '../../shared/types';
import * as T from '../../shared/styles/tokens';

// Statuses the user can assign (backend VALID_STATUSES minus the rarely
// used pinned/hooked which fleet does not surface).
const STATUS_OPTIONS = ['open', 'in_progress', 'blocked', 'deferred', 'closed'];

// Status dropdown, unblock and remove-assignee buttons for one bead.
export function BeadActions({ bead }: { bead: BeadDetail }) {
  const setStatus = useSetBeadStatus();
  const unblock = useUnblockBead();
  const removeAssignee = useRemoveBeadAssignee();
  const busy = setStatus.isPending || unblock.isPending || removeAssignee.isPending;

  return (
    <div style={styles.controls}>
      <label style={styles.controlLabel}>
        Status
        <select
          style={styles.select}
          value={bead.status}
          disabled={busy}
          onChange={(e) => setStatus.mutate({ id: bead.id, status: e.target.value })}
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
          {!STATUS_OPTIONS.includes(bead.status) && (
            <option value={bead.status}>{bead.status}</option>
          )}
        </select>
      </label>
      {bead.status === 'blocked' && (
        <button style={styles.unblockBtn} disabled={busy} onClick={() => unblock.mutate(bead.id)}>
          Unblock
        </button>
      )}
      {bead.assignee && (
        <button
          style={styles.unassignBtn}
          disabled={busy}
          onClick={() => {
            if (!window.confirm(`Remove assignee "${bead.assignee}" from ${bead.id}?`)) return;
            removeAssignee.mutate(bead.id);
          }}
        >
          Remove assignee
        </button>
      )}
    </div>
  );
}

const styles = {
  controls: {
    display: 'flex', alignItems: 'flex-end', gap: '0.625rem', flexWrap: 'wrap' as const,
    padding: '0.75rem', background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`, borderRadius: 6, marginBottom: '1rem',
  } as React.CSSProperties,
  controlLabel: {
    display: 'flex', flexDirection: 'column' as const, gap: '0.25rem', fontSize: '0.7rem',
    color: T.colors.textDim, textTransform: 'uppercase' as const, letterSpacing: '0.05em',
  } as React.CSSProperties,
  select: {
    padding: '0.25rem 0.5rem', background: T.colors.bgDeep, border: `1px solid ${T.colors.border}`,
    borderRadius: 4, color: T.colors.textPrimary, fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif', cursor: 'pointer',
  } as React.CSSProperties,
  unblockBtn: {
    padding: '0.3rem 0.75rem', background: 'transparent', border: '1px solid #2563eb',
    borderRadius: 4, color: '#60a5fa', cursor: 'pointer', fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  unassignBtn: {
    padding: '0.3rem 0.75rem', background: 'transparent', border: '1px solid #78716c',
    borderRadius: 4, color: '#a8a29e', cursor: 'pointer', fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
