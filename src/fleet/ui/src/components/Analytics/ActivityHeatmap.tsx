import { useMemo } from 'react';
import * as T from '../../styles/tokens';

interface ActivityHeatmapProps {
  heatmap: number[][];
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const TICK_HOURS = [0, 6, 12, 18];

function fmtCount(n: number): string {
  if (n === 0) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

export function ActivityHeatmap({ heatmap }: ActivityHeatmapProps) {
  const { maxCount, rows } = useMemo(() => {
    let max = 0;
    for (let r = 0; r < Math.min(heatmap.length, 7); r++) {
      const row = heatmap[r];
      if (Array.isArray(row)) {
        for (let c = 0; c < Math.min(row.length, 24); c++) {
          if (row[c] > max) max = row[c];
        }
      }
    }
    return {
      maxCount: max,
      rows: heatmap.slice(0, 7).map(r => (Array.isArray(r) ? r.slice(0, 24) : [])),
    };
  }, [heatmap]);

  return (
    <div style={panel}>
      <div style={title}>Activity by hour</div>
      <div style={outer}>
        <div style={tickRow}>
          <div style={tickCorner} />
          {Array.from({ length: 24 }, (_, i) => (
            <div key={i} style={tickCell}>
              {TICK_HOURS.includes(i) ? String(i).padStart(2, '0') : ''}
            </div>
          ))}
        </div>
        {rows.map((row, ri) => (
          <div key={ri} style={dayRow}>
            <div style={dayLabel}>{DAYS[ri]}</div>
            {row.map((count, ci) => {
              const alpha = maxCount > 0 ? (count / maxCount) * 0.94 + 0.06 : 0.06;
              const bg = count > 0
                ? `rgba(59,130,246,${alpha.toFixed(3)})`
                : 'rgba(59,130,246,0.04)';
              return (
                <div
                  key={ci}
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 2,
                    background: bg,
                    flexShrink: 0,
                  }}
                  title={`${DAYS[ri]} ${String(ci).padStart(2, '0')}:00 — ${fmtCount(count)}`}
                />
              );
            })}
          </div>
        ))}
        <div style={hourAxis}>
          <div style={{
            width: 48,
            fontSize: '0.5rem',
            color: T.colors.textMuted,
          }}>
            hour
          </div>
          {Array.from({ length: 24 }, (_, i) => (
            <div key={i} style={{
              fontSize: '0.5rem',
              color: T.colors.textMuted,
              textAlign: 'left' as const,
              flex: i === 23 ? 'none' : 1,
              maxWidth: 12,
              minWidth: i === 23 ? 12 : 0,
              overflow: 'visible',
              whiteSpace: 'nowrap',
            }}>
              {TICK_HOURS.includes(i) ? `H${String(i).padStart(2, '0')}` : ''}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const panel: React.CSSProperties = {
  ...T.panel,
  padding: '0.75rem 1rem',
  width: '100%',
  overflowX: 'auto',
};

const title: React.CSSProperties = {
  fontSize: '0.6875rem',
  fontWeight: 600,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.05em',
  color: T.colors.textMuted,
  marginBottom: '0.5rem',
};

const outer: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column' as const,
  gap: 2,
};

const tickRow: React.CSSProperties = {
  display: 'flex',
  gap: 2,
  marginBottom: 2,
};

const tickCorner: React.CSSProperties = {
  width: 48,
  flexShrink: 0,
};

const tickCell: React.CSSProperties = {
  width: 12,
  height: 0,
  fontSize: '0.5rem',
  color: T.colors.textMuted,
  textAlign: 'center' as const,
};

const dayRow: React.CSSProperties = {
  display: 'flex',
  gap: 2,
};

const dayLabel: React.CSSProperties = {
  width: 48,
  height: 12,
  fontSize: '0.5625rem',
  color: T.colors.textDim,
  display: 'flex',
  alignItems: 'center',
  flexShrink: 0,
};

const hourAxis: React.CSSProperties = {
  display: 'flex',
  gap: 2,
  marginTop: 2,
};

