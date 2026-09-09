import type { AnalyticsToolRow } from '../../../shared/types';
import * as T from '../../../shared/styles/tokens';
import * as P from '../chartTheme';
import { formatCount } from '../../../shared/format';
import { merge } from '../../../shared/styles/recipes';

interface ToolUsageBarProps {
  tools: { total: number; rows: AnalyticsToolRow[] };
}

const ROW_HEIGHT = 22;
const TRACK_HEIGHT = 8;
const MAX_NAME_WIDTH = '9rem';
const MAX_ROWS = 12;

export function ToolUsageBar({ tools }: ToolUsageBarProps) {
  const { total, rows } = tools;

  const top = (rows || [])
    .slice()
    .sort((a, b) => b.count - a.count)
    .slice(0, MAX_ROWS);

  const maxCount = Math.max(...top.map(r => r.count), 1);

  return (
    <div style={panel}>
      <div style={P.panelTitle}>
        <span>Tool usage</span>
        {total > 0 && <span style={P.panelTitleAside}>{formatCount(total)} calls</span>}
      </div>
      {top.length === 0 ? (
        <p style={P.panelEmpty}>No tool data in this window.</p>
      ) : (
        <>
          {top.map(row => (
            <div key={row.name} style={rowContainer}>
              <span
                style={styles.toolName}
                title={row.name}
              >
                {row.name}
              </span>
              <div style={track}>
                <div
                  style={merge(fill, { width: `${(row.count / maxCount) * 100}%`,  })}
                />
              </div>
              <span style={styles.toolCount}>
                {formatCount(row.count)}
              </span>
            </div>
          ))}
          {rows.length > MAX_ROWS && (
            <div style={more}>+{rows.length - MAX_ROWS} more tools</div>
          )}
        </>
      )}
    </div>
  );
}

const panel: React.CSSProperties = {
  ...P.panel,
  flex: '1.3 1 340px',
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
  borderRadius: '0.25rem',
  overflow: 'hidden',
};

const fill: React.CSSProperties = {
  height: '100%',
  background: T.colors.accent,
  borderRadius: '0.25rem',
};

const more: React.CSSProperties = {
  fontSize: '0.75rem',
  color: T.colors.textMuted,
  fontStyle: 'italic' as const,
  marginTop: '0.25rem',
  textAlign: 'right' as const,
};

const styles = {
  toolName: {
    fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
    fontSize: '0.75rem',
    color: T.colors.textSecondary,
    width: MAX_NAME_WIDTH,
    textAlign: 'right' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    flexShrink: 0,
  } as React.CSSProperties,
  toolCount: {
    fontSize: '0.75rem', color: T.colors.textDim, width: '3.5rem',
    textAlign: 'right' as const, flexShrink: 0,
  } as React.CSSProperties,
};
