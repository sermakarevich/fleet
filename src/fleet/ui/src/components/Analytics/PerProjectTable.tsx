import { useState, useCallback } from 'react';
import type { AnalyticsByModelProject } from '../../types';
import { fmtDuration, fmtTokens, fmtPct } from './format';

interface Props {
  rows: AnalyticsByModelProject[];
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
  { key: 'success_rate', label: 'Success', numeric: false },
  { key: 'median_run_sec', label: 'Median run', numeric: true },
  { key: 'output_tokens', label: 'Output tok', numeric: true },
];

function projectFromCwd(r: AnalyticsByModelProject): string {
  return (r.model || '').split('/').filter(Boolean).pop() ?? (r.model || '\u2014');
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

  const handleSort = useCallback(() => {
    setSortKey(prev => {
      if (prev === sortKey) {
        setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        return prev;
      }
      setSortDir('desc');
      return prev;
    });
  }, [sortKey]);

  const sorted = [...rows].sort((a, b) => {
    const col = COLUMNS.find(c => c.key === sortKey)!;
    let cmp = 0;
    if (col.key === 'cwd') {
      cmp = projectFromCwd(a).localeCompare(projectFromCwd(b));
    } else if (col.numeric) {
      cmp = nullLast(a[col.key], b[col.key]);
    } else {
      cmp = 0;
    }
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const sortIndicator = (colKey: ColumnKey) => {
    if (sortKey !== colKey) return '\u239C';
    return sortDir === 'desc' ? '\u25BC' : '\u25B3';
  };

  const successBarFor = (rate: number) => {
    const pct = Math.round(rate * 100);
    return (
      <span style={styles.successCell}>
        <span style={styles.track}>
          <span style={{ ...styles.fill, width: `${pct}%`, background: pct > 50 ? '#22c55e' : '#71717a' }} />
        </span>
        <span style={styles.pctText}>{fmtPct(rate)}</span>
      </span>
    );
  };

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>By project</h3>
      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  onClick={col.numeric || col.key === 'cwd' ? handleSort : undefined}
                  style={{
                    ...styles.th,
                    cursor: col.numeric || col.key === 'cwd' ? 'pointer' : 'default',
                  }}
                >
                  {col.label} {col.numeric || col.key === 'cwd' ? sortIndicator(col.key) : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : '#1c1c20' }}>
                <td style={styles.td} title={r.coder || r.model || ''}>
                  {projectFromCwd(r)}
                </td>
                <td style={{ ...styles.td, textAlign: 'right' }}>{r.total}</td>
                <td style={styles.td}>{successBarFor(r.success_rate)}</td>
                <td style={{ ...styles.td, textAlign: 'right' }}>{fmtDuration(r.median_run_sec)}</td>
                <td style={{ ...styles.td, textAlign: 'right' }}>{fmtTokens(r.output_tokens)}</td>
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
    flex: '1 1 500px',
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
  successCell: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
    width: '100%',
  } as React.CSSProperties,
  track: {
    width: '48px',
    height: '6px',
    background: '#27272a',
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
