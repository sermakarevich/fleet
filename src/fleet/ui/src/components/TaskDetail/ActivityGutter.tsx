import { useEffect, useState } from 'react';
import { Sparkline } from '../Sparkline';
import type { FleetEvent, TaskDetail } from '../../types';
import { useKillTask } from '../../hooks/useApi';
import { useNavigate } from 'react-router-dom';

interface Props {
  task: TaskDetail;
  events: FleetEvent[];
}

function fmtIdle(sec: number | null): string {
  if (sec == null) return '—';
  if (sec < 5) return 'just now';
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  return `${Math.floor(sec / 60)}m ago`;
}

function kindColor(kind: string): string {
  switch (kind) {
    case 'tool_use': return '#3b82f6';
    case 'tool_result': return '#22c55e';
    case 'api_request': return '#8b5cf6';
    case 'api_response': return '#a855f7';
    case 'error': return '#ef4444';
    default: return '#71717a';
  }
}

export function ActivityGutter({ task, events }: Props) {
  const { mutate: kill, isPending } = useKillTask();
  const navigate = useNavigate();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

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

  function handleKill() {
    if (!canKill) return;
    kill(task.id, { onSuccess: () => navigate('/') });
  }

  return (
    <div style={styles.gutter}>
      <div style={styles.section}>
        <div style={styles.label}>tokens</div>
        <Sparkline value={tokenTotal ?? null} />
        {tokenTotal != null && (
          <div style={styles.value}>{tokenTotal.toLocaleString()}</div>
        )}
      </div>

      <div style={styles.section}>
        <div style={styles.label}>idle</div>
        <div style={styles.value}>{fmtIdle(idleSec)}</div>
      </div>

      {lastEventKind && (
        <div style={styles.section}>
          <div style={styles.label}>last event</div>
          <span style={{ ...styles.kindChip, background: kindColor(lastEventKind) }}>
            {lastEventKind}
          </span>
        </div>
      )}

      {canKill && (
        <div style={styles.killSection}>
          <button
            style={{ ...styles.killBtn, opacity: isPending ? 0.5 : 1 }}
            onClick={handleKill}
            disabled={isPending}
          >
            {isPending ? 'Killing…' : 'Kill'}
          </button>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  gutter: {
    width: 200,
    flexShrink: 0,
    borderLeft: '1px solid #27272a',
    background: '#18181b',
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
    color: '#52525b',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  value: {
    color: '#a1a1aa',
    fontFamily: 'monospace',
  },
  kindChip: {
    display: 'inline-block',
    padding: '0.1rem 0.4rem',
    borderRadius: 3,
    color: '#fff',
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
    background: '#7f1d1d',
    border: '1px solid #991b1b',
    borderRadius: 4,
    color: '#fca5a5',
    fontSize: '0.8rem',
    fontWeight: 600,
    cursor: 'pointer',
  },
};
