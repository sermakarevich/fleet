import type { SupervisorStatus } from '../../types';
import * as T from '../../styles/tokens';

interface Props {
  status: SupervisorStatus;
  onPause: () => void;
  onResume: () => void;
  onRestart: () => Promise<void>;
  loading: boolean;
}

export function SupervisorPanel({ status, onPause, onResume, onRestart, loading }: Props) {
  const startedAt = status.started_at
    ? new Date(status.started_at).toLocaleString()
    : '—';

  const handleRestart = async () => {
    if (!window.confirm('Restart the supervisor daemon?')) return;
    await onRestart();
  };

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={status.running ? styles.dotRunning : styles.dotStopped} />
        <h3 style={styles.title}>Supervisor</h3>
        {status.paused && <span style={styles.pausedBadge}>paused</span>}
        {!status.running && <span style={styles.stoppedBadge}>stopped</span>}
        {status.stale && <span style={styles.staleBadge}>stale</span>}
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
        <button
          style={status.stale ? styles.restartBtnStale : styles.restartBtn}
          onClick={handleRestart}
          disabled={loading}
        >
          Restart
        </button>
      </div>
    </div>
  );
}

const styles = {
  panel: {
    ...T.panel,
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
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  dotRunning: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: '#22c55e',
    flexShrink: 0,
  } as React.CSSProperties,
  dotStopped: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: '#6b7280',
    flexShrink: 0,
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
  stoppedBadge: {
    padding: '0.15rem 0.5rem',
    background: '#374151',
    borderRadius: 9999,
    fontSize: '0.7rem',
    fontWeight: 600,
    color: '#9ca3af',
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
    color: T.colors.textDim,
  } as React.CSSProperties,
  dd: {
    margin: 0,
    color: T.colors.textPrimary,
    fontVariantNumeric: 'tabular-nums',
  } as React.CSSProperties,
  actions: {
    marginTop: '0.875rem',
    display: 'flex',
    gap: '0.5rem',
  } as React.CSSProperties,
  pauseBtn: {
    ...T.btnGhost,
    padding: '0.35rem 0.875rem',
    border: '1px solid #f59e0b',
    color: '#fbbf24',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  resumeBtn: {
    ...T.btnGhost,
    padding: '0.35rem 0.875rem',
    border: '1px solid #22c55e',
    color: '#4ade80',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  restartBtn: {
    ...T.btnGhost,
    padding: '0.35rem 0.875rem',
    border: '1px solid #6b7280',
    color: '#9ca3af',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  restartBtnStale: {
    ...T.btnGhost,
    padding: '0.35rem 0.875rem',
    border: '1px solid #f59e0b',
    color: '#fbbf24',
    fontSize: '0.8125rem',
    fontWeight: 600,
  } as React.CSSProperties,
  staleBadge: {
    padding: '0.15rem 0.5rem',
    background: 'rgba(245,158,11,0.15)',
    border: '1px solid #f59e0b',
    borderRadius: 9999,
    fontSize: '0.7rem',
    fontWeight: 600,
    color: '#fbbf24',
    letterSpacing: '0.02em',
  } as React.CSSProperties,
};
