// Supervisor status card for the settings page: liveness, slot counts,
// pause / resume and restart (restart asks through the shared Confirm,
// never window.confirm). Rendered by SupervisorSection.
import { useState } from 'react';
import type { SupervisorStatus } from '../../shared/types';
import { formatDateTime } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import { Confirm } from '../../shared/ui/Confirm';

interface Props {
  status: SupervisorStatus;
  onPause: () => void;
  onResume: () => void;
  onRestart: () => Promise<void>;
  loading: boolean;
}

export function SupervisorPanel({ status, onPause, onResume, onRestart, loading }: Props) {
  const startedAt = formatDateTime(status.started_at);
  const [confirmRestart, setConfirmRestart] = useState(false);

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
        {confirmRestart ? (
          <Confirm
            verb="Restart"
            onConfirm={() => {
              setConfirmRestart(false);
              void onRestart();
            }}
            onCancel={() => setConfirmRestart(false)}
          />
        ) : (
          <button
            style={status.stale ? styles.restartBtnStale : styles.restartBtn}
            onClick={() => setConfirmRestart(true)}
            disabled={loading}
          >
            Restart
          </button>
        )}
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
    width: '0.5rem',
    height: '0.5rem',
    borderRadius: '50%',
    background: T.colors.success,
    flexShrink: 0,
  } as React.CSSProperties,
  dotStopped: {
    width: '0.5rem',
    height: '0.5rem',
    borderRadius: '50%',
    background: T.colors.gray,
    flexShrink: 0,
  } as React.CSSProperties,
  pausedBadge: {
    padding: '0.15rem 0.5rem',
    background: T.colors.purpleDark,
    borderRadius: '10rem',
    fontSize: '0.7rem',
    fontWeight: 600,
    color: T.colors.lavenderPale,
    letterSpacing: '0.02em',
  } as React.CSSProperties,
  stoppedBadge: {
    padding: '0.15rem 0.5rem',
    background: T.colors.slateDark,
    borderRadius: '10rem',
    fontSize: '0.7rem',
    fontWeight: 600,
    color: T.colors.grayLight,
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
    border: `1px solid ${T.colors.amber}`,
    color: T.colors.amberLight,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  resumeBtn: {
    ...T.btnGhost,
    padding: '0.35rem 0.875rem',
    border: `1px solid ${T.colors.success}`,
    color: T.colors.diffAddFg,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  restartBtn: {
    ...T.btnGhost,
    padding: '0.35rem 0.875rem',
    border: `1px solid ${T.colors.gray}`,
    color: T.colors.grayLight,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  restartBtnStale: {
    ...T.btnGhost,
    padding: '0.35rem 0.875rem',
    border: `1px solid ${T.colors.amber}`,
    color: T.colors.amberLight,
    fontSize: '0.8125rem',
    fontWeight: 600,
  } as React.CSSProperties,
  staleBadge: {
    padding: '0.15rem 0.5rem',
    background: T.colors.warningBg,
    border: `1px solid ${T.colors.amber}`,
    borderRadius: '10rem',
    fontSize: '0.7rem',
    fontWeight: 600,
    color: T.colors.warningFg,
    letterSpacing: '0.02em',
  } as React.CSSProperties,
};
