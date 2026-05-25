import type { PerProjectRow } from '../../types';

function basename(cwd: string): string {
  return cwd.split('/').filter(Boolean).pop() ?? cwd;
}

function fmtElapsed(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

interface Props {
  rows: PerProjectRow[];
}

export function PerProjectTable({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div style={styles.container}>
        <h3 style={styles.title}>Per Project</h3>
        <p style={styles.empty}>No project data yet.</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>Per Project</h3>
      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              {['Project', 'Tasks', 'Success%', 'Mean elapsed'].map(col => (
                <th key={col} style={styles.th}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : '#1c1c20' }}>
                <td style={{ ...styles.td, color: '#a1a1aa' }} title={r.cwd}>{basename(r.cwd)}</td>
                <td style={styles.td}>{r.task_count}</td>
                <td style={styles.td}>{(r.success_rate * 100).toFixed(1)}%</td>
                <td style={styles.td}>{fmtElapsed(r.mean_elapsed_sec)}</td>
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
