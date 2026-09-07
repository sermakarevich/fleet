import type { AnalyticsKpis } from '../../../shared/types';
import * as T from '../../../shared/styles/tokens';
import { seriesColors } from '../chartTheme';
import { fmtDuration, fmtTokens, fmtPct } from '../../../shared/format';

interface CardProps {
  kpis: AnalyticsKpis;
}

const CARD: React.CSSProperties = {
  ...T.panel,
  padding: '0.75rem 0.875rem',
  display: 'flex',
  flexDirection: 'column' as const,
  gap: '0.25rem',
  minWidth: 0,
};

interface Item {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}

export function KpiCards({ kpis }: CardProps) {
  const errors = kpis.error_events ?? 0;
  const rateLimited = kpis.rate_limited_tasks ?? 0;
  const cacheTotal =
    ((kpis.total_cache_read_tokens ?? 0) + (kpis.total_cache_creation_tokens ?? 0)) || null;

  const items: Item[] = [
    { label: 'Completed', value: String(kpis.completed) },
    {
      label: 'Success rate',
      value: fmtPct(kpis.success_rate),
      color:
        kpis.success_rate >= 0.8
          ? seriesColors.success
          : kpis.success_rate >= 0.5
            ? seriesColors.blocked
            : seriesColors.failed,
    },
    { label: 'Active now', value: String(kpis.active_now) },
    { label: 'Queued', value: String(kpis.queued) },
    {
      label: 'Median run',
      value: fmtDuration(kpis.median_run_sec),
      sub: kpis.p90_run_sec != null ? `p90 ${fmtDuration(kpis.p90_run_sec)}` : undefined,
    },
    { label: 'Median wait', value: fmtDuration(kpis.median_queue_wait_sec) },
    { label: 'Output tokens', value: fmtTokens(kpis.total_output_tokens) },
    { label: 'Input tokens', value: fmtTokens(kpis.total_input_tokens ?? null) },
    { label: 'Cache tokens', value: fmtTokens(cacheTotal) },
    {
      label: 'Errors',
      value: String(errors),
      color: errors > 0 ? seriesColors.failed : undefined,
    },
    {
      label: 'Rate limited',
      value: String(rateLimited),
      color: rateLimited > 0 ? seriesColors.blocked : undefined,
    },
    { label: 'Respawns/task', value: kpis.avg_segments != null ? kpis.avg_segments.toFixed(1) : '—' },
  ];

  return (
    <div className="kpi-grid">
      {items.map(card => (
        <div key={card.label} style={CARD}>
          <div style={{
            fontSize: '1.25rem',
            fontWeight: 600,
            color: card.color ?? T.colors.textPrimary,
            lineHeight: 1.2,
            whiteSpace: 'nowrap' as const,
          }}>
            {card.value}
          </div>
          <div style={{ fontSize: '0.6875rem', color: T.colors.textMuted, letterSpacing: '0.04em', textTransform: 'uppercase' as const }}>
            {card.label}
            {card.sub && (
              <span style={{ color: T.colors.textDim, textTransform: 'none' as const, letterSpacing: 'normal', marginLeft: '0.375rem' }}>
                · {card.sub}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
