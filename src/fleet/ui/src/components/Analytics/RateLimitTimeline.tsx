import type { BurnoutRow, RateLimitEvent } from '../../types';

function fmtTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

interface Props {
  burnouts: BurnoutRow[];
  rateLimits: RateLimitEvent[];
}

export function RateLimitTimeline({ burnouts, rateLimits }: Props) {
  return (
    <div style={styles.container}>
      <div style={styles.col}>
        <h3 style={styles.title}>Context Burnouts</h3>
        {burnouts.length === 0 ? (
          <p style={styles.empty}>No context pressure events.</p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                {['Coder', 'Model', 'Count'].map(col => (
                  <th key={col} style={styles.th}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {burnouts.map((r, i) => (
                <tr key={i}>
                  <td style={styles.td}>{r.coder}</td>
                  <td style={{ ...styles.td, color: '#71717a' }}>{r.model}</td>
                  <td style={styles.td}>{r.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={styles.col}>
        <h3 style={styles.title}>Rate Limit Events</h3>
        {rateLimits.length === 0 ? (
          <p style={styles.empty}>No rate limit events.</p>
        ) : (
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  {['Time', 'Provider', 'Duration'].map(col => (
                    <th key={col} style={styles.th}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rateLimits.map((r, i) => (
                  <tr key={i}>
                    <td style={{ ...styles.td, color: '#71717a', whiteSpace: 'nowrap' }}>{fmtTs(r.ts)}</td>
                    <td style={styles.td}>{r.provider}</td>
                    <td style={styles.td}>{r.duration_sec != null ? `${Math.round(r.duration_sec)}s` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  container: {
    display: 'flex',
    gap: '2rem',
    marginBottom: '1.5rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  col: {
    flex: 1,
    minWidth: '14rem',
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.75rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  tableWrap: {
    overflowX: 'auto',
  } as React.CSSProperties,
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  th: {
    textAlign: 'left',
    padding: '0.4rem 0.75rem',
    color: '#71717a',
    borderBottom: '1px solid #27272a',
    fontWeight: 500,
    whiteSpace: 'nowrap',
  } as React.CSSProperties,
  td: {
    padding: '0.4rem 0.75rem',
    color: '#e4e4e7',
    borderBottom: '1px solid #27272a',
  } as React.CSSProperties,
  empty: {
    color: '#52525b',
    fontSize: '0.875rem',
    margin: 0,
  } as React.CSSProperties,
};
