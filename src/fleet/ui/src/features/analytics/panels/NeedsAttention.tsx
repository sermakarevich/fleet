import { useNavigate } from 'react-router-dom';
import { formatHourMinute, formatMonthDay } from '../../../shared/format';
import * as T from '../../../shared/styles/tokens';
import * as P from '../chartTheme';
import { useClickableProps } from '../../../shared/ui/Clickable';
import { merge } from '../../../shared/styles/recipes';

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
  noclose: T.colors.clay,
  context_pressure: T.colors.clay,
  rate_limited: T.colors.accent,
};

function formatEndedAt(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${formatMonthDay(date)} ${formatHourMinute(date)}`;
}

export function NeedsAttention({ rows }: Props) {
  return (
    <div style={merge(P.panel, { flex: '1 1 30rem', minWidth: 0 })}>
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
                <th scope="col" style={styles.th}>Status</th>
                <th scope="col" style={styles.th}>ID</th>
                <th scope="col" style={styles.th}>Title</th>
                <th scope="col" style={styles.th}>Ended</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <AttentionRow key={r.id} row={r} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// One attention row: keyboard-operable, navigates to the task on activate.
function AttentionRow({ row: r }: { row: Props['rows'][number] }) {
  const navigate = useNavigate();
  const rowClick = useClickableProps(() => navigate('/tasks/' + r.id));
  const key = (r.outcome || '').toLowerCase();
  const chipColor = outColors[key] || T.colors.link;
  return (
    <tr
      className="row-interactive"
      {...rowClick}
      style={styles.tr}
    >
      <td style={styles.td}>
        <span style={merge(styles.chip, { background: chipColor + '20', color: chipColor })}>
          {(r.outcome || '—').replace(/_/g, ' ')}
        </span>
      </td>
      <td style={merge(styles.td, styles.monospace, { color: T.colors.link })}>
        {r.id.slice(0, 8)}
      </td>
      <td style={merge(styles.td, styles.ellipsis)}>
        {r.title}
      </td>
      <td style={merge(styles.td, styles.monospace, { color: T.colors.textDim, whiteSpace: 'nowrap' })}>
        {formatEndedAt(r.ended_at)}
      </td>
    </tr>
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
