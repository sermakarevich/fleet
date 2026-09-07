import { useMemo } from 'react';
import * as T from '../../../shared/styles/tokens';
import * as P from '../chartTheme';
import { fmtCount } from '../../../shared/format';

interface ActivityHeatmapProps {
  heatmap: number[][];
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const TICK_HOURS = [0, 6, 12, 18];

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
    <div style={{ ...P.panel, flex: '1 1 420px', overflowX: 'auto' }}>
      <div style={P.panelTitle}>
        <span>Activity by hour</span>
      </div>
      {rows.length === 0 || maxCount === 0 ? (
        <p style={P.panelEmpty}>No activity in this window.</p>
      ) : (
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
                      ...cell,
                      background: bg,
                    }}
                    title={`${DAYS[ri]} ${String(ci).padStart(2, '0')}:00 — ${fmtCount(count)}`}
                  />
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

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

// Cells and hour ticks share one flex sizing rule so the ticks stay above their
// own column when the grid stretches to fill the panel.
const cellFlex: React.CSSProperties = {
  flex: '1 1 12px',
  minWidth: 12,
  maxWidth: 22,
};

const cell: React.CSSProperties = {
  ...cellFlex,
  height: 12,
  borderRadius: 2,
};

const tickCell: React.CSSProperties = {
  ...cellFlex,
  height: 12,
  fontSize: '0.5625rem',
  color: T.colors.textDim,
  textAlign: 'center' as const,
  overflow: 'visible',
  whiteSpace: 'nowrap' as const,
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
