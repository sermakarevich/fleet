interface Props {
  events: { ts: string; task_id: string }[];
}

const MAX_VISIBLE = 30;

function fmtShort(ts: string): string {
  try {
    var d = new Date(ts);
    var mon = d.toLocaleString('en-US', { month: 'short' });
    var dd = String(d.getDate()).padStart(2, '0');
    var hh = String(d.getHours()).padStart(2, '0');
    var mm = String(d.getMinutes()).padStart(2, '0');
    return mon + ' ' + dd + ' ' + hh + ':' + mm;
  } catch {
    return ts;
  }
}

export function RateLimitTimeline({ events }: Props) {
  if (events.length === 0) {
    return (
      <div style={styles.container}>
        <h3 style={styles.title}>Rate-limit rejections</h3>
        <p style={styles.empty}>No rate-limit rejections in this window.</p>
      </div>
    );
  }

  var truncated = events.length > MAX_VISIBLE;
  var display = truncated ? events.slice(-MAX_VISIBLE) : events;

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>Rate-limit rejections</h3>
      <div style={styles.strip}>
        {display.map(function (e, i) {
          return (
            <div key={i} style={styles.event}>
              <span style={styles.ts}>{fmtShort(e.ts)}</span>
              <span style={styles.monospace}>{e.task_id}</span>
            </div>
          );
        })}
        {truncated && (
          <div style={styles.more}>+(
            {events.length - MAX_VISIBLE}{' '}
            earlier)</div>
        )}
      </div>
    </div>
  );
}

const styles = {
  container: {
    flex: '1 1 30rem',
    minWidth: '14rem',
    display: 'flex',
    flexDirection: 'column' as const,
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.75rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  empty: {
    color: '#52525b',
    fontSize: '0.875rem',
    margin: 0,
  } as React.CSSProperties,
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
    color: '#d4d4d9',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  ts: {
    color: '#71717a',
  } as React.CSSProperties,
  monospace: {
    fontFamily: 'ui-monospace, monospace',
    color: '#60a5fa',
  } as React.CSSProperties,
  more: {
    fontSize: '0.75rem',
    color: '#52525b',
    fontStyle: 'italic' as const,
    marginTop: '0.125rem',
  } as React.CSSProperties,
};
