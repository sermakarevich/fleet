import type { AnalyticsKpis } from '../../types';
import * as T from '../../styles/tokens';
import { fmtDuration, fmtTokens, fmtPct } from './format';

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

export function KpiCards({ kpis }: CardProps) {
  const items: Array<{ label: string; value: string; color?: string }> = [
    { label: 'Completed', value: String(kpis.completed) },
    { label: 'Success rate', value: fmtPct(kpis.success_rate), color: kpis.success_rate >= 0.8 ? '#16a34a' : kpis.success_rate >= 0.5 ? '#ca8a04' : '#dc2626' },
    { label: 'Active now', value: String(kpis.active_now) },
    { label: 'Queued', value: String(kpis.queued) },
    { label: 'Median run', value: fmtDuration(kpis.median_run_sec) },
    { label: 'Median wait', value: fmtDuration(kpis.median_queue_wait_sec) },
    { label: 'Output tokens', value: fmtTokens(kpis.total_output_tokens) },
    { label: 'Input tokens', value: fmtTokens(kpis.total_input_tokens ?? null) },
    { label: 'Cache tokens', value: fmtTokens(((kpis.total_cache_read_tokens ?? 0) + (kpis.total_cache_creation_tokens ?? 0)) || null) },
    { label: 'Respawns/task', value: kpis.avg_segments != null ? kpis.avg_segments.toFixed(1) : '\u2014' },
  ];

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
      gap: '0.625rem',
    }}>
      {items.map(card => (
        <div key={card.label} style={CARD}>
          <div style={{
            fontSize: '1.25rem',
            fontWeight: 600,
            color: card.color ?? T.colors.textPrimary,
            lineHeight: 1.2,
          }}>
            {card.value}
          </div>
          <div style={{ fontSize: '0.6875rem', color: T.colors.textMuted, letterSpacing: '0.04em', textTransform: 'uppercase' as const }}>
            {card.label}
          </div>
        </div>
      ))}
    </div>
  );
}
