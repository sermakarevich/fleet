import type { SupervisorStatus } from '../../types';

interface Props {
  status: SupervisorStatus;
  onPause: () => void;
  onResume: () => void;
  loading: boolean;
}

export function SupervisorPanel({ status, onPause, onResume, loading }: Props) {
  const startedAt = status.started_at
    ? new Date(status.started_at).toLocaleString()
    : '—';

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <h3 style={styles.title}>Supervisor</h3>
        {status.paused && <span style={styles.pausedBadge}>paused</span>}
      </div>
      <dl style={styles.dl}>
        <div style={styles.dlRow}>
          <dt style={styles.dt}>PID</dt>
          <dd style={styles.dd}>{status.pid ?? '—'}</dd>
        </div>
        <div style={styles.dlRow}>
          <dt style={styles.dt}>Started</dt>
          <dd style={styles.dd}>{startedAt}</dd>
        </div>
        <div style={styles.dlRow}>
          <dt style={styles.dt}>Max concurrent</dt>
          <dd style={styles.dd}>{status.max_concurrent}</dd>
        </div>
        <div style={styles.dlRow}>
          <dt style={styles.dt}>Active / Free slots</dt>
          <dd style={styles.dd}>{status.active_count} / {status.free_slots}</dd>
        </div>
      </dl>
      <div style={styles.actions}>
        {status.paused ? (
          <button style={styles.resumeBtn} onClick={onResume} disabled={loading}>
            Resume
          </button>
        ) : (
          <button style={styles.pauseBtn} onClick={onPause} disabled={loading}>
            Pause
          </button>
        )}
      </div>
    </div>
  );
}

const styles = {
  panel: {
    background: '#1c1c20',
    border: '1px solid #3f3f46',
    borderRadius: 8,
    padding: '1rem 1.25rem',
    marginBottom: '1rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginBottom: '0.75rem',
  } as React.CSSProperties,
  title: {
    margin: 0,
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  pausedBadge: {
    padding: '0.15rem 0.5rem',
    background: '#7c3aed',
    borderRadius: 9999,
    fontSize: '0.7rem',
    fontWeight: 600,
    color: '#ede9fe',
    letterSpacing: '0.02em',
  } as React.CSSProperties,
  dl: {
    margin: 0,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.3rem',
  } as React.CSSProperties,
  dlRow: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '1rem',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  dt: {
    color: '#71717a',
  } as React.CSSProperties,
  dd: {
    margin: 0,
    color: '#e4e4e7',
    fontVariantNumeric: 'tabular-nums',
  } as React.CSSProperties,
  actions: {
    marginTop: '0.875rem',
    display: 'flex',
    gap: '0.5rem',
  } as React.CSSProperties,
  pauseBtn: {
    padding: '0.35rem 0.875rem',
    background: 'transparent',
    border: '1px solid #f59e0b',
    borderRadius: 4,
    color: '#fbbf24',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  resumeBtn: {
    padding: '0.35rem 0.875rem',
    background: 'transparent',
    border: '1px solid #22c55e',
    borderRadius: 4,
    color: '#4ade80',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
