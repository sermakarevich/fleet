import * as T from '../../../shared/styles/tokens';
import * as P from '../chartTheme';
import { fmtCount } from '../../../shared/format';

const BUCKET_LABELS = ['0-25', '25-50', '50-75', '75-100', '100+'];
const LABEL_COLORS: Record<number, string> = {
  3: P.seriesColors.blocked,
  4: P.seriesColors.failed,
};
const MIN_HEIGHT_PX = 2;
// Total height of the chart row (count label + bar area + bucket label + gaps).
const CHART_HEIGHT_PX = 140;

interface ContextHistogramProps {
  buckets: number[] | Record<string, number>;
}

export function ContextHistogram({ buckets }: ContextHistogramProps) {
  // Backend sends buckets as an object keyed by label ({"0-25": n, ...}); older/array shape also OK.
  const counts: number[] = Array.isArray(buckets)
    ? buckets
    : BUCKET_LABELS.map((l) => buckets[l] ?? 0);
  const maxCount = Math.max(...counts, 1);

  return (
    <div style={panel}>
      <div style={P.panelTitle}>
        <span>Peak context vs limit</span>
      </div>
      <div style={flexRow}>
        {counts.map((count, i) => {
          const heightPct = (count / maxCount) * 100;
          const color = LABEL_COLORS[i] ?? T.colors.accent;

          return (
            <div key={BUCKET_LABELS[i]} style={bucketWrapper}>
              <div style={countLabel}>{fmtCount(count)}</div>
              <div style={barContainer}>
                <div
                  style={{
                    width: '100%',
                    height: `${heightPct}%`,
                    minHeight: `${MIN_HEIGHT_PX}px`,
                    background: color,
                    borderRadius: '4px 4px 0 0',
                  }}
                />
              </div>
              <div style={bucketLabel}>{BUCKET_LABELS[i]}%</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const panel: React.CSSProperties = {
  ...P.panel,
  flex: '1 1 280px',
  display: 'flex',
  flexDirection: 'column' as const,
};

// Grows into whatever height the row's tallest panel sets, never below the floor.
const flexRow: React.CSSProperties = {
  display: 'flex',
  alignItems: 'stretch',
  gap: '0.75rem',
  flex: 1,
  minHeight: `${CHART_HEIGHT_PX}px`,
};

const bucketWrapper: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column' as const,
  alignItems: 'center',
  gap: '0.25rem',
};

const countLabel: React.CSSProperties = {
  fontSize: '0.6875rem',
  color: T.colors.textDim,
  height: '1rem',
  lineHeight: '1rem',
  flexShrink: 0,
  whiteSpace: 'nowrap' as const,
};

const barContainer: React.CSSProperties = {
  flex: 1,
  width: '100%',
  display: 'flex',
  flexDirection: 'column' as const,
  justifyContent: 'flex-end',
  alignItems: 'center',
  overflow: 'hidden',
};

const bucketLabel: React.CSSProperties = {
  fontSize: '0.6875rem',
  color: T.colors.textDim,
  textAlign: 'center' as const,
  flexShrink: 0,
  height: '1rem',
  lineHeight: '1rem',
  whiteSpace: 'nowrap' as const,
};
