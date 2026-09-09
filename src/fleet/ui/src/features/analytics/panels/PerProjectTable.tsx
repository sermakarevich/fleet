import { useState, useCallback } from 'react';
import type { AnalyticsByProjectRow } from '../../../shared/types';
import * as T from '../../../shared/styles/tokens';
import * as P from '../chartTheme';
import { formatDuration, formatTokens, formatPercent } from '../../../shared/format';
import { altRowStyle, merge } from '../../../shared/styles/recipes';

interface Props {
  rows: AnalyticsByProjectRow[];
}

type ColumnKey = 'cwd' | 'total' | 'success_rate' | 'median_run_sec' | 'output_tokens';

interface Column {
  key: ColumnKey;
  label: string;
  numeric: boolean;
}

const COLUMNS: Column[] = [
  { key: 'cwd', label: 'Project', numeric: false },
  { key: 'total', label: 'Tasks', numeric: true },
  { key: 'success_rate', label: 'Success', numeric: true },
  { key: 'median_run_sec', label: 'Median run', numeric: true },
  { key: 'output_tokens', label: 'Output tok', numeric: true },
];

function projectFromCwd(r: AnalyticsByProjectRow): string {
  return (r.cwd || '').split('/').filter(Boolean).pop() ?? (r.cwd || '—');
}

function nullLast(a: number | null, b: number | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return a - b;
}

export function PerProjectTable({ rows }: Props) {
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
    if (col.key === 'cwd') {
      cmp = projectFromCwd(a).localeCompare(projectFromCwd(b));
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
          <span style={merge(styles.fill, { width: `${pct}%`, background: pct > 50 ? P.seriesColors.success : '#71717a' })} />
        </span>
        <span style={styles.pctText}>{formatPercent(rate)}</span>
      </span>
    );
  };

  return (
    <div style={merge(P.panel, { flex: '1 1 380px' })}>
      <div style={P.panelTitle}>
        <span>By project</span>
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
                    scope="col"
                    aria-sort={sortKey === col.key ? (sortDir === 'desc' ? 'descending' : 'ascending') : 'none'}
                    style={styles.th}
                  >
                    <button
                      style={styles.sortBtn}
                      onClick={() => handleSort(col.key)}
                      aria-label={`Sort by ${col.label}`}
                    >
                      {col.label} {sortIndicator(col.key)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => (
                <tr key={i} style={altRowStyle(i)}>
                  <td style={styles.td} title={r.cwd || ''}>
                    {projectFromCwd(r)}
                  </td>
                  <td style={merge(styles.td, { textAlign: 'right' })}>{r.total}</td>
                  <td style={styles.td}>{successBarFor(r.success_rate)}</td>
                  <td style={merge(styles.td, { textAlign: 'right' })}>{formatDuration(r.median_run_sec)}</td>
                  <td style={merge(styles.td, { textAlign: 'right' })}>{formatTokens(r.output_tokens)}</td>
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
    padding: '0.4rem 0.75rem',
    color: T.colors.textDim,
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontWeight: 500,
    whiteSpace: 'nowrap',
    userSelect: 'none',
  } as React.CSSProperties,
  sortBtn: {
    background: 'none',
    border: 'none',
    padding: 0,
    color: 'inherit',
    font: 'inherit',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  } as React.CSSProperties,
  td: {
    padding: '0.4rem 0.75rem',
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
};
