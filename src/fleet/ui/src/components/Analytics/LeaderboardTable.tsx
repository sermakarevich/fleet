import type { LeaderboardRow } from '../../types';

function fmtElapsed(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

function fmtTokens(n: number): string {
  if (n < 1000) return String(Math.round(n));
  if (n < 1e6) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1e6).toFixed(2)}M`;
}

interface Props {
  rows: LeaderboardRow[];
}

export function LeaderboardTable({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div style={styles.container}>
        <h3 style={styles.title}>Coder Leaderboard</h3>
        <p style={styles.empty}>No completed tasks with coder data yet.</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>Coder Leaderboard</h3>
      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              {['Coder', 'Model', 'Success%', 'Mean elapsed', 'Mean tokens'].map(col => (
                <th key={col} style={styles.th}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : '#1c1c20' }}>
                <td style={styles.td}>{r.coder}</td>
                <td style={{ ...styles.td, color: '#71717a' }}>{r.model}</td>
                <td style={styles.td}>{(r.success_rate * 100).toFixed(1)}%</td>
                <td style={styles.td}>{fmtElapsed(r.mean_elapsed_sec)}</td>
                <td style={styles.td}>{fmtTokens(r.mean_tokens)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const styles = {
  container: {
    marginBottom: '1.5rem',
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
