import * as T from '../../styles/tokens';

const BUCKET_LABELS = ['0-25', '25-50', '50-75', '75-100', '100+'];
const LABEL_COLORS: Record<number, string> = {
  3: '#d97706',
  4: '#dc2626',
};
const MIN_HEIGHT_PX = 2;
// Total height of the chart row (count label + bar area + bucket label + gaps).
const CHART_HEIGHT_PX = 140;

function fmtCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

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
      <div style={title}>Peak context vs limit</div>
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
  ...T.panel,
  padding: '0.75rem 1rem',
  minWidth: '320px',
  flex: '1 1 320px',
  maxWidth: '480px',
};

const title: React.CSSProperties = {
  fontSize: '0.6875rem',
  fontWeight: 600,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.05em',
  color: T.colors.textMuted,
  marginBottom: '0.5rem',
};

const flexRow: React.CSSProperties = {
  display: 'flex',
  alignItems: 'stretch',
  gap: '0.75rem',
  height: `${CHART_HEIGHT_PX}px`,
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
