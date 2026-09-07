import { useNavigate } from 'react-router-dom';
import * as T from '../../../shared/styles/tokens';
import * as P from '../chartTheme';

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

// Chip colors per attention label: failed/blocked reuse the status trio;
// noclose/context_pressure are "degraded" (warm coral); rate_limited is
// informational (accent blue).
const outColors: Record<string, string> = {
  failed: P.seriesColors.failed,
  blocked: P.seriesColors.blocked,
  noclose: '#ec835a',
  context_pressure: '#ec835a',
  rate_limited: '#3b82f6',
};

function fmtEnded(ts: string | null): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const date = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${date} ${time}`;
}

export function NeedsAttention({ rows }: Props) {
  const navigate = useNavigate();

  return (
    <div style={{ ...P.panel, flex: '1 1 30rem', minWidth: 0 }}>
      <div style={P.panelTitle}>
        <span>Needs attention</span>
      </div>
      {rows.length === 0 ? (
        <p style={P.panelEmpty}>Nothing needs attention in this window 🎉</p>
      ) : (
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
              {rows.map(r => {
                const key = (r.outcome || '').toLowerCase();
                const chipColor = outColors[key] || '#60a5fa';
                return (
                  <tr
                    key={r.id}
                    className="row-interactive"
                    tabIndex={0}
                    onClick={() => navigate('/tasks/' + r.id)}
                    style={styles.tr}
                  >
                    <td style={styles.td}>
                      <span style={{ ...styles.chip, background: chipColor + '20', color: chipColor }}>
                        {(r.outcome || '—').replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td style={{ ...styles.td, ...styles.monospace, color: '#60a5fa' }}>
                      {r.id.slice(0, 8)}
                    </td>
                    <td style={{ ...styles.td, ...styles.ellipsis }}>
                      {r.title}
                    </td>
                    <td style={{ ...styles.td, ...styles.monospace, color: T.colors.textDim, whiteSpace: 'nowrap' }}>
                      {fmtEnded(r.ended_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const styles = {
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
    color: T.colors.textDim,
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontWeight: 500,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  td: {
    padding: '0.4rem 0.75rem',
    color: T.colors.textPrimary,
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
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
  } as React.CSSProperties,
  chip: {
    display: 'inline-block',
    padding: '0.125rem 0.5rem',
    borderRadius: '4px',
    fontSize: '0.75rem',
    fontWeight: 500,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
};
