import { useEffect, useState } from 'react';
import { Sparkline } from '../../../../shared/ui/Sparkline';
import type { FleetEvent, TaskDetail } from '../../../../shared/types';
import { formatIdle, formatInteger } from '../../../../shared/format';
import { useNow } from '../../../../shared/hooks/useNow';
import { useKillTask } from '../../../../shared/hooks/useApi';
import { eventKindColor } from '../../../../shared/colors';
import { merge } from '../../../../shared/styles/recipes';
import * as T from '../../../../shared/styles/tokens';

interface Props {
  task: TaskDetail;
  events: FleetEvent[];
}

export function ActivityGutter({ task, events }: Props) {
  const { mutate: kill, isPending } = useKillTask();
  const now = useNow();
  const [isStopping, setIsStopping] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (task.status !== 'in_progress' && task.status !== 'blocked') {
      setIsStopping(false);
      setConfirming(false);
    }
  }, [task.status]);

  const lastEvent = events[events.length - 1] ?? null;
  const lastEventKind = lastEvent?.kind ?? task.last_event_kind;

  // Token count from events (use usage field from api_response events)
  const lastUsageEvent = [...events].reverse().find(e => e.usage != null);
  const tokenTotal = lastUsageEvent?.usage
    ? (lastUsageEvent.usage.input_tokens ?? 0) + (lastUsageEvent.usage.output_tokens ?? 0)
    : task.context_tokens;

  // Idle: compute from last ws event or fallback to task.idle_sec
  const lastEventTs = lastEvent?.ts ? new Date(lastEvent.ts).getTime() : null;
  const idleSec = lastEventTs ? (now - lastEventTs) / 1000 : task.idle_sec;

  const canKill = ['in_progress', 'blocked'].includes(task.status);

  function handleKillClick() {
    if (!canKill) return;
    setConfirming(true);
  }

  function handleKillConfirm() {
    setConfirming(false);
    setIsStopping(true);
    kill(task.id, { onError: () => setIsStopping(false) });
  }

  function handleKillCancel() {
    setConfirming(false);
  }

  return (
    <div style={styles.gutter}>
      <div style={styles.section}>
        <div style={styles.label}>tokens</div>
        <Sparkline value={tokenTotal ?? null} />
        {tokenTotal != null && (
          <div style={styles.value}>{formatInteger(tokenTotal ?? null)}</div>
        )}
      </div>

      <div style={styles.section}>
        <div style={styles.label}>idle</div>
        <div style={styles.value}>{formatIdle(idleSec)}</div>
      </div>

      {lastEventKind && (
        <div style={styles.section}>
          <div style={styles.label}>last event</div>
          <span style={merge(styles.kindChip, { background: eventKindColor(lastEventKind) })}>
            {lastEventKind}
          </span>
        </div>
      )}

      {canKill && (
        <div style={styles.killSection}>
          {!confirming && !isPending && !isStopping && (
            <button style={styles.killBtn} onClick={handleKillClick}>
              Kill
            </button>
          )}
          {confirming && (
            <div style={styles.confirmWrap}>
              <span style={styles.confirmLabel}>Confirm kill?</span>
              <div style={styles.confirmBtns}>
                <button style={styles.yesBtn} onClick={handleKillConfirm}>Yes</button>
                <button style={styles.cancelBtn} onClick={handleKillCancel}>Cancel</button>
              </div>
            </div>
          )}
          {(isPending || isStopping) && (
            <button style={merge(styles.killBtn, { opacity: 0.5 })} disabled>
              {isPending ? 'Killing…' : 'Stopping…'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  gutter: {
    width: 200,
    flexShrink: 0,
    borderLeft: `1px solid ${T.colors.borderSubtle}`,
    background: T.colors.bgSurface,
    padding: '0.75rem 0.75rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '1rem',
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.78rem',
    overflowY: 'auto',
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.25rem',
  },
  label: {
    fontSize: '0.65rem',
    fontWeight: 600,
    color: T.colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  value: {
    color: T.colors.textSecondary,
    fontFamily: 'monospace',
  },
  kindChip: {
    display: 'inline-block',
    padding: '0.1rem 0.4rem',
    borderRadius: 3,
    color: T.colors.white,
    fontSize: '0.65rem',
    fontWeight: 700,
    alignSelf: 'flex-start',
  },
  killSection: {
    marginTop: 'auto',
  },
  killBtn: {
    width: '100%',
    padding: '0.4rem',
    background: T.colors.maroon,
    border: `1px solid ${T.colors.redDeep}`,
    borderRadius: '0.25rem',
    color: T.colors.roseLight,
    fontSize: '0.8rem',
    fontWeight: 600,
    cursor: 'pointer',
  },
  confirmWrap: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.375rem',
  },
  confirmLabel: {
    fontSize: '0.72rem',
    color: T.colors.textSecondary,
    whiteSpace: 'nowrap' as const,
  },
  confirmBtns: {
    display: 'flex',
    gap: '0.375rem',
  },
  yesBtn: {
    flex: 1,
    padding: '0.3rem 0.4rem',
    background: T.colors.redDeep,
    border: `1px solid ${T.colors.redDeep}`,
    borderRadius: '0.25rem',
    color: T.colors.white,
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontWeight: 600,
  },
  cancelBtn: {
    flex: 1,
    padding: '0.3rem 0.4rem',
    background: 'transparent',
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.75rem',
  },
};
