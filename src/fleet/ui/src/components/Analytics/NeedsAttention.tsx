import { useNavigate } from 'react-router-dom';

interface Props {
  rows: {
    id: string;
    title: string;
    coder: string | null;
    model: string | null;
    outcome: string | null;
    ended_at: string | null;
  }[];
}

const outColors: Record<string, string> = {
  failed: '#dc2626',
  blocked: '#d97706',
};

function fmtTime(ts: string | null): string {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return ts;
  }
}

export function NeedsAttention({ rows }: Props) {
  const navigate = useNavigate();

  if (rows.length === 0) {
    return (
      <div style={styles.container}>
        <h3 style={styles.title}>Needs attention</h3>
        <p style={styles.empty}>No failures in this window 🎉</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>Needs attention</h3>
      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Status</th>
              <th style={styles.th}>ID</th>
              <th style={styles.th}>Title</th>
              <th style={styles.th}>Ended</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(function (r) {
              var chipColor = r.outcome ? (outColors[r.outcome.toLowerCase()] || '#60a5fa') : '#60a5fa';
              return (
                <tr
                  key={r.id}
                  className="row-interactive"
                  tabIndex={0}
                  onClick={function () { navigate('/tasks/' + r.id); }}
                  style={styles.tr}
                >
                  <td style={styles.td}>
                    <span style={Object.assign({}, styles.chip, { background: chipColor + '20', color: chipColor })}>
                      {r.outcome || '—'}
                    </span>
                  </td>
                  <td style={Object.assign({}, styles.td, styles.monospace, { color: '#60a5fa' })}>
                    {r.id.slice(0, 8)}
                  </td>
                  <td style={Object.assign({}, styles.td, styles.ellipsis)}>
                    {r.title}
                  </td>
                  <td style={Object.assign({}, styles.td, styles.monospace, { color: '#71717a' })}>
                    {fmtTime(r.ended_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const styles = {
  container: {
    flex: '1 1 30rem',
    minWidth: '30rem',
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
  tableWrap: {
    overflowX: 'auto',
  } as React.CSSProperties,
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  th: {
    textAlign: 'left' as const,
    padding: '0.4rem 0.75rem',
    color: '#71717a',
    borderBottom: '1px solid #27272a',
    fontWeight: 500,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  td: {
    padding: '0.4rem 0.75rem',
    color: '#e4e4e7',
    borderBottom: '1px solid #27272a',
  } as React.CSSProperties,
  tr: {
    cursor: 'pointer',
  } as React.CSSProperties,
  monospace: {
    fontFamily: 'ui-monospace, monospace',
  } as React.CSSProperties,
  ellipsis: {
    maxWidth: '14rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    flex: 1,
  } as React.CSSProperties,
  chip: {
    display: 'inline-block',
    padding: '0.125rem 0.5rem',
    borderRadius: '4px',
    fontSize: '0.75rem',
    fontWeight: 500,
  } as React.CSSProperties,
};
