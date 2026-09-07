import type { TaskAttempt } from '../../types';

interface Props {
  attempts: TaskAttempt[];
}

function formatTs(ts: string | null): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts.replace('Z', '+00:00'));
    if (isNaN(d.getTime())) return ts;
    return d.toTimeString().slice(0, 8);
  } catch {
    return ts;
  }
}

function formatDuration(sec: number | null, endedAt: string | null): string {
  if (endedAt == null) return 'running';
  if (sec == null) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function RunsTab({ attempts }: Props) {
  const sorted = [...attempts].sort((a, b) => b.n - a.n);

  if (sorted.length === 0) {
    return (
      <div style={styles.container}>
        <p style={styles.msg}>No runs recorded yet (history starts with the first spawn after this feature was deployed).</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.list}>
        <table style={styles.table}>
          <thead>
            <tr>
              {['#', 'Started', 'Duration', 'Coder / model', 'Outcome', 'Fleet action', 'Reason'].map(h => (
                <th key={h} style={styles.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(a => (
              <tr key={a.n} style={styles.row}>
                <td style={styles.td}>{a.n}</td>
                <td style={styles.td}>{formatTs(a.started_at)}</td>
                <td style={styles.td}>{formatDuration(a.duration_sec, a.ended_at)}</td>
                <td style={styles.td}>{[a.coder, a.model].filter(Boolean).join(' / ') || '—'}</td>
                <td style={styles.td}>{a.outcome ?? '—'}</td>
                <td style={styles.td}>{a.action ?? '—'}</td>
                <td style={{ ...styles.td, ...styles.reasonCell }} title={a.reason ?? undefined}>{a.reason ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    fontFamily: 'monospace',
    fontSize: '0.78rem',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.25rem 0.5rem',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.78rem',
  },
  th: {
    padding: '0.3rem 0.5rem',
    textAlign: 'left',
    color: '#71717a',
    fontWeight: 500,
    borderBottom: '1px solid #27272a',
    whiteSpace: 'nowrap',
  },
  row: {
    borderBottom: '1px solid #1c1c20',
  },
  td: {
    padding: '0.25rem 0.5rem',
    color: '#e4e4e7',
    verticalAlign: 'middle',
    whiteSpace: 'nowrap',
  },
  reasonCell: {
    maxWidth: '20rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    color: '#a1a1aa',
  },
  msg: {
    padding: '0.5rem',
    color: '#71717a',
    margin: 0,
  },
};
