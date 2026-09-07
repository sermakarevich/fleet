import { useState, useCallback } from 'react';
import type { AnalyticsByModelProject } from '../../../shared/types';
import * as T from '../../../shared/styles/tokens';
import * as P from '../chartTheme';
import { fmtDuration, fmtTokens, fmtPct } from '../../../shared/format';

interface Props {
  rows: AnalyticsByModelProject[];
}

type ColumnKey = 'model' | 'total' | 'success_rate' | 'median_run_sec' | 'mean_peak_context_tokens' | 'output_tokens' | 'avg_segments' | 'errors';

interface Column {
  key: ColumnKey;
  label: string;
  numeric: boolean;
}

const COLUMNS: Column[] = [
  { key: 'model', label: 'Coder · Model', numeric: false },
  { key: 'total', label: 'Tasks', numeric: true },
  { key: 'success_rate', label: 'Success', numeric: true },
  { key: 'median_run_sec', label: 'Median run', numeric: true },
  { key: 'mean_peak_context_tokens', label: 'Peak ctx', numeric: true },
  { key: 'output_tokens', label: 'Output tok', numeric: true },
  { key: 'avg_segments', label: 'Segs', numeric: true },
  { key: 'errors', label: 'Errors', numeric: true },
];

function nullLast(a: number | null, b: number | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return a - b;
}

export function LeaderboardTable({ rows }: Props) {
  const [sortKey, setSortKey] = useState<ColumnKey>('total');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const handleSort = useCallback((colKey: ColumnKey) => {
    if (colKey === sortKey) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(colKey);
      setSortDir('desc');
    }
  }, [sortKey]);

  const sorted = [...rows].sort((a, b) => {
    const col = COLUMNS.find(c => c.key === sortKey)!;
    let cmp = 0;
    if (col.key === 'model') {
      cmp = (a.model || '').localeCompare(b.model || '');
      if (cmp === 0) cmp = (a.coder || '').localeCompare(b.coder || '');
    } else if (col.numeric) {
      cmp = nullLast(a[col.key], b[col.key]);
    }
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const sortIndicator = (colKey: ColumnKey) => {
    if (sortKey !== colKey) return null;
    return sortDir === 'desc' ? '▼' : '△';
  };

  const successBarFor = (rate: number) => {
    const pct = Math.round(rate * 100);
    return (
      <span style={styles.successCell}>
        <span style={styles.track}>
          <span style={{ ...styles.fill, width: `${pct}%`, background: pct > 50 ? P.seriesColors.success : '#71717a' }} />
        </span>
        <span style={styles.pctText}>{fmtPct(rate)}</span>
      </span>
    );
  };

  return (
    <div style={{ ...P.panel, flex: '1.5 1 520px' }}>
      <div style={P.panelTitle}>
        <span>By model</span>
      </div>
      {rows.length === 0 ? (
        <p style={P.panelEmpty}>No completed tasks in this window.</p>
      ) : (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                {COLUMNS.map(col => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    style={{ ...styles.th, cursor: 'pointer' }}
                  >
                    {col.label} {sortIndicator(col.key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : T.colors.bgElevated }}>
                  <td style={{ ...styles.td, whiteSpace: 'nowrap' }}>
                    {r.coder ? <span style={styles.coderPrefix}>{r.coder} · </span> : null}
                    <span style={styles.modelName}>{r.model || '—'}</span>
                  </td>
                  <td style={{ ...styles.td, textAlign: 'right' }}>{r.total}</td>
                  <td style={styles.td}>{successBarFor(r.success_rate)}</td>
                  <td style={{ ...styles.td, textAlign: 'right' }}>{fmtDuration(r.median_run_sec)}</td>
                  <td style={{ ...styles.td, textAlign: 'right' }}>{fmtTokens(r.mean_peak_context_tokens)}</td>
                  <td style={{ ...styles.td, textAlign: 'right' }}>{fmtTokens(r.output_tokens)}</td>
                  <td style={{ ...styles.td, textAlign: 'right' }}>{r.avg_segments != null ? r.avg_segments.toFixed(1) : '—'}</td>
                  <td style={{ ...styles.td, textAlign: 'right', color: r.errors > 0 ? P.seriesColors.failed : undefined }}>
                    {r.errors}
                  </td>
                </tr>
              ))}
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
    borderCollapse: 'collapse',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  th: {
    textAlign: 'left',
    padding: '0.4rem 0.5rem',
    color: T.colors.textDim,
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontWeight: 500,
    whiteSpace: 'nowrap',
    userSelect: 'none',
  } as React.CSSProperties,
  td: {
    padding: '0.4rem 0.5rem',
    color: T.colors.textPrimary,
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  successCell: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
    width: '100%',
  } as React.CSSProperties,
  track: {
    width: '48px',
    height: '6px',
    background: T.colors.borderSubtle,
    borderRadius: '3px',
    overflow: 'hidden',
  } as React.CSSProperties,
  fill: {
    height: '100%',
    borderRadius: '3px',
  } as React.CSSProperties,
  pctText: {
    fontSize: '0.8125rem',
    whiteSpace: 'nowrap',
  } as React.CSSProperties,
  coderPrefix: {
    color: T.colors.textDim,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  modelName: {
    color: T.colors.textSecondary,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
};
