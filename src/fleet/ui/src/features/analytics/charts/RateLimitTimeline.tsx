import * as T from '../../../shared/styles/tokens';
import * as P from '../chartTheme';

interface Props {
  events: { ts: string; task_id: string }[];
}

const MAX_VISIBLE = 30;

function fmtShort(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const mon = d.toLocaleString('en-US', { month: 'short' });
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${mon} ${dd} ${hh}:${mm}`;
}

export function RateLimitTimeline({ events }: Props) {
  const truncated = events.length > MAX_VISIBLE;
  const display = truncated ? events.slice(-MAX_VISIBLE) : events;

  return (
    <div style={{ ...P.panel, flex: '1 1 30rem', minWidth: 0 }}>
      <div style={P.panelTitle}>
        <span>Rate-limit rejections</span>
        {events.length > 0 && <span style={P.panelTitleAside}>{events.length} total</span>}
      </div>
      {events.length === 0 ? (
        <p style={P.panelEmpty}>No rate-limit rejections in this window.</p>
      ) : (
        <div style={styles.strip}>
          {display.map((e, i) => (
            <div key={i} style={styles.event}>
              <span style={styles.ts}>{fmtShort(e.ts)}</span>
              <span style={styles.monospace}>{e.task_id}</span>
            </div>
          ))}
          {truncated && (
            <div style={styles.more}>+{events.length - MAX_VISIBLE} earlier</div>
          )}
        </div>
      )}
    </div>
  );
}

const styles = {
  strip: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.25rem',
    overflowX: 'auto',
  } as React.CSSProperties,
  event: {
    display: 'flex',
    gap: '0.75rem',
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  ts: {
    color: T.colors.textDim,
    fontFamily: 'ui-monospace, monospace',
  } as React.CSSProperties,
  monospace: {
    fontFamily: 'ui-monospace, monospace',
    color: '#60a5fa',
  } as React.CSSProperties,
  more: {
    fontSize: '0.75rem',
    color: T.colors.textMuted,
    fontStyle: 'italic' as const,
    marginTop: '0.125rem',
  } as React.CSSProperties,
};
