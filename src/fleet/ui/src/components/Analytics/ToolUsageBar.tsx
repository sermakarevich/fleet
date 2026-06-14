import type { AnalyticsToolRow } from '../../types';
import * as T from '../../styles/tokens';

interface ToolUsageBarProps {
  tools: { total: number; rows: AnalyticsToolRow[] };
}

const ROW_HEIGHT = 22;
const TRACK_HEIGHT = 8;
const MAX_NAME_WIDTH = '9rem';

function fmtCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function ToolUsageBar({ tools }: ToolUsageBarProps) {
  const { total, rows } = tools;

  if (!rows || rows.length === 0) {
    return (
      <div style={panel}>
        <div style={title}>Tool usage</div>
        <div style={empty}>No tool data</div>
      </div>
    );
  }

  const top = rows
    .slice()
    .sort((a, b) => b.count - a.count)
    .slice(0, 12);

  const maxCount = Math.max(...top.map(r => r.count), 1);

  let totalRows = 0;
  top.forEach(r => { totalRows += r.count; });

  return (
    <div style={panel}>
      <div style={title}>Tool usage</div>
      <div style={totalBar}>
        <span style={{ fontSize: '0.75rem', fontWeight: 600, color: T.colors.textPrimary }}>
          {fmtCount(total)}
        </span>
        <div style={totalTrack}>
          <div
            style={{
              ...totalFill,
              width: `${Math.min(totalRows / maxCount * 100, 100)}%`,
              background: T.colors.accent,
            }}
          />
        </div>
      </div>
      {top.map(row => (
        <div key={row.name} style={rowContainer}>
          <span
            style={{
              fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
              fontSize: '0.75rem',
              color: T.colors.textSecondary,
              width: MAX_NAME_WIDTH,
              textAlign: 'right' as const,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
            title={row.name}
          >
            {row.name}
          </span>
          <div style={track}>
            <div
              style={{
                ...fill,
                width: `${(row.count / maxCount) * 100}%`,
                background: T.colors.accent,
              }}
            />
          </div>
          <span style={{ fontSize: '0.75rem', color: T.colors.textDim, width: '3.5rem', textAlign: 'right' as const, flexShrink: 0 }}>
            {fmtCount(row.count)}
          </span>
        </div>
      ))}
    </div>
  );
}

const panel: React.CSSProperties = {
  ...T.panel,
  padding: '0.75rem 1rem',
  minWidth: '360px',
  flex: '1 1 360px',
  maxWidth: '520px',
};

const title: React.CSSProperties = {
  fontSize: '0.6875rem',
  fontWeight: 600,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.05em',
  color: T.colors.textMuted,
  marginBottom: '0.5rem',
};

const empty: React.CSSProperties = {
  fontSize: '0.8125rem',
  color: T.colors.textDim,
  padding: '1.5rem 0',
  textAlign: 'center' as const,
};

const totalBar: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '0.5rem',
  marginBottom: '0.375rem',
};

const totalTrack: React.CSSProperties = {
  flex: 1,
  height: TRACK_HEIGHT,
  background: 'rgba(59,130,246,0.08)',
  borderRadius: 4,
  overflow: 'hidden',
};

const totalFill: React.CSSProperties = {
  height: TRACK_HEIGHT,
  background: T.colors.accent,
  borderRadius: 4,
};

const rowContainer: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  height: ROW_HEIGHT,
  gap: '0.5rem',
};

const track: React.CSSProperties = {
  flex: 1,
  height: TRACK_HEIGHT,
  background: 'rgba(59,130,246,0.08)',
  borderRadius: 4,
  overflow: 'hidden',
};

const fill: React.CSSProperties = {
  height: '100%',
  background: T.colors.accent,
  borderRadius: 4,
};
