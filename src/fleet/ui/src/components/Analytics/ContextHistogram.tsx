import * as T from '../../styles/tokens';

const BUCKET_LABELS = ['0-25', '25-50', '50-75', '75-100', '100+'];
const LABEL_COLORS: Record<number, string> = {
  3: '#d97706',
  4: '#dc2626',
};
const MAX_HEIGHT_PX = 120;
const MIN_HEIGHT_PX = 2;

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
          const heightPct = maxCount > 0 ? (count / maxCount) * 100 : 0;
          const color = LABEL_COLORS[i] ?? T.colors.accent;
          const barHeight = count === 0 ? `${MIN_HEIGHT_PX}px` : `${Math.max((heightPct / 100) * MAX_HEIGHT_PX, MIN_HEIGHT_PX)}px`;

          return (
            <div key={BUCKET_LABELS[i]} style={bucketWrapper}>
              <div style={countLabel}>{fmtCount(count)}</div>
              <div style={barContainer}>
                <div
                  style={{
                    height: barHeight,
                    background: color,
                    borderRadius: '4px 4px 0 0',
                    marginBottom: 'auto',
                  }}
                />
              </div>
              <div style={label}>{BUCKET_LABELS[i]}%</div>
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
  alignItems: 'flex-end',
  gap: '0.75rem',
  height: `${MAX_HEIGHT_PX}px`,
};

const bucketWrapper: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column' as const,
  alignItems: 'center',
  gap: '0.25rem',
  height: '100%',
};

const countLabel: React.CSSProperties = {
  fontSize: '0.6875rem',
  color: T.colors.textDim,
  height: '1rem',
  flexShrink: 0,
};

const barContainer: React.CSSProperties = {
  width: '2rem',
  height: '100%',
  display: 'flex',
  alignItems: 'flex-end',
  justifyContent: 'center',
};

const label: React.CSSProperties = {
  fontSize: '0.6875rem',
  color: T.colors.textDim,
  textAlign: 'center' as const,
  flexShrink: 0,
};
