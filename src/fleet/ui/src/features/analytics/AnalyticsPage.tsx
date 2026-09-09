import { useState, useEffect, useMemo } from 'react';
import { useAnalyticsSummary } from '../../shared/hooks/useApi';
import { KpiCards } from './charts/KpiCards';
import { ThroughputChart } from './charts/ThroughputChart';
import { TokenUsageChart } from './charts/TokenUsageChart';
import { LeaderboardTable } from './panels/LeaderboardTable';
import { PerProjectTable } from './panels/PerProjectTable';
import { ToolUsageBar } from './charts/ToolUsageBar';
import { ContextHistogram } from './charts/ContextHistogram';
import { ActivityHeatmap } from './charts/ActivityHeatmap';
import { NeedsAttention } from './panels/NeedsAttention';
import { RateLimitTimeline } from './charts/RateLimitTimeline';
import { fillBuckets } from './timeBuckets';
import { storageGet, storageSet } from '../../shared/storage';
import type { AnalyticsKpis } from '../../shared/types';
import * as T from '../../shared/styles/tokens';
import { merge, when } from '../../shared/styles/recipes';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';

const RANGE_OPTIONS = [
  { label: '24h', days: 1 },
  { label: '3d', days: 3 },
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: 'All', days: 0 },
];

const DEFAULT_KPIS: AnalyticsKpis = {
  completed: 0,
  success_rate: 0,
  active_now: 0,
  queued: 0,
  median_run_sec: null,
  p90_run_sec: null,
  median_queue_wait_sec: null,
  total_output_tokens: null,
  total_steps: null,
  avg_segments: null,
  error_events: null,
  noclose_count: null,
  rate_limited_tasks: null,
};

function readDefaultRange(): number {
  const raw = storageGet('fleet.analytics.range');
  const n = raw ? Number(raw) : NaN;
  if (RANGE_OPTIONS.some(o => o.days === n)) return n;
  return 7;
}

export function AnalyticsPage() {
  const [days, setDays] = useState(readDefaultRange);

  useEffect(() => {
    storageSet('fleet.analytics.range', String(days));
  }, [days]);

  const { data, isLoading, error } = useAnalyticsSummary(days);

  // The server decides bucket granularity (hour for short windows, day
  // otherwise) — trust it instead of re-deriving from `days`.
  const bucketSize: 'hour' | 'day' =
    data?.throughput?.bucket_size === 'hour' ? 'hour' : 'day';

  const throughputBuckets = useMemo(() => {
    if (!data) return [];
    return fillBuckets(
      data.throughput.buckets,
      bucketSize,
      { success: 0, failed: 0, blocked: 0 },
      days,
    );
  }, [data, bucketSize, days]);

  const tokenBuckets = useMemo(() => {
    if (!data?.token_throughput) return [];
    return fillBuckets(
      data.token_throughput.buckets,
      bucketSize,
      { output_tokens: 0, input_tokens: 0, cache_tokens: 0 },
      days,
    );
  }, [data, bucketSize, days]);

  const rateLimitEvents = useMemo(() => {
    if (!data) return [];
    return data.rate_limits.map(r => ({ ts: r.ts, task_id: r.task_id }));
  }, [data]);

  if (isLoading) return <LoadingState message="Loading analytics…" />;
  if (error) return <p style={styles.err}>Error: {String(error)}</p>;

  const kpis = data?.kpis ?? DEFAULT_KPIS;

  return (
    <PageShell
      title="Analytics"
      actions={
        <div style={styles.filterRow}>
          {RANGE_OPTIONS.map(opt => (
            <button
              key={opt.label}
              style={merge(styles.filterBtn, when(days === opt.days, styles.filterBtnActive))}
              onClick={() => setDays(opt.days)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      }
    >
      <div style={styles.col}>
      <KpiCards kpis={kpis} />
      <ThroughputChart bucketSize={bucketSize} buckets={throughputBuckets} />
      <TokenUsageChart bucketSize={bucketSize} buckets={tokenBuckets} />
      <div style={styles.row}>
        <LeaderboardTable rows={data?.by_model ?? []} />
        <PerProjectTable rows={data?.by_project ?? []} />
      </div>
      <div style={styles.row}>
        <ToolUsageBar tools={data?.tools ?? { total: 0, rows: [] }} />
        <ContextHistogram buckets={data?.context_histogram?.buckets ?? []} />
        <ActivityHeatmap heatmap={data?.heatmap ?? []} />
      </div>
      <div style={styles.row}>
        <NeedsAttention rows={data?.errors_recent ?? []} />
        <RateLimitTimeline events={rateLimitEvents} />
      </div>
      </div>
    </PageShell>
  );
}

const styles = {
  col: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.875rem',
  } as React.CSSProperties,
  err: {
    padding: '1rem',
    color: T.colors.danger,
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  filterRow: {
    display: 'flex',
    gap: '0.375rem',
    flexWrap: 'wrap',
  } as React.CSSProperties,
  filterBtn: {
    ...T.btnGhost,
    padding: '0.2rem 0.625rem',
    fontSize: '0.8125rem',
    color: T.colors.textDim,
    lineHeight: 1.4,
  } as React.CSSProperties,
  filterBtnActive: {
    background: T.colors.accent,
    borderColor: T.colors.accent,
    color: T.colors.white,
  } as React.CSSProperties,
  row: {
    display: 'flex',
    gap: '0.875rem',
    flexWrap: 'wrap',
    alignItems: 'stretch',
  } as React.CSSProperties,
};
