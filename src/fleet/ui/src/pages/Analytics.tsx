import { useState, useEffect, useMemo } from 'react';
import { useAnalyticsSummary } from '../hooks/useApi';
import { KpiCards } from '../components/Analytics/KpiCards';
import { ThroughputChart } from '../components/Analytics/ThroughputChart';
import { TokenUsageChart } from '../components/Analytics/TokenUsageChart';
import { LeaderboardTable } from '../components/Analytics/LeaderboardTable';
import { PerProjectTable } from '../components/Analytics/PerProjectTable';
import { ToolUsageBar } from '../components/Analytics/ToolUsageBar';
import { ContextHistogram } from '../components/Analytics/ContextHistogram';
import { ActivityHeatmap } from '../components/Analytics/ActivityHeatmap';
import type { AnalyticsKpis } from '../types';
import * as T from '../styles/tokens';

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
  try {
    const raw = localStorage.getItem('fleet.analytics.range');
    const n = raw ? Number(raw) : null;
    if (n != null) {
      var allowed = RANGE_OPTIONS.map(function (o) { return o.days; });
      if (allowed.indexOf(n) !== -1) return n;
    }
  } catch (_e) { /* ignore */ }
  return 7;
}

export function Analytics() {
  var _s = useState(readDefaultRange);
  var days = _s[0];
  var setDays = _s[1];

  useEffect(function () {
    localStorage.setItem('fleet.analytics.range', String(days));
  }, [days]);

  var _q = useAnalyticsSummary(days);
  var data = _q.data;
  var isLoading = _q.isLoading;
  var error = _q.error;

  var bucketSize = useMemo(function () {
    if (days <= 1) return 'hour' as const;
    return 'day' as const;
  }, [days]);

  var throughputBuckets = useMemo(function () {
    if (!data) return [];
    return data.throughput.buckets.map(function (b) {
      return { bucket: b.bucket, success: b.success, failed: b.failed, blocked: b.blocked };
    });
  }, [data]);

  var tokenBuckets = useMemo(function () {
    if (!data || !data.token_throughput) return [];
    return data.token_throughput.buckets;
  }, [data]);

  var byModelRows = useMemo(function () {
    if (!data) return [];
    return data.by_model;
  }, [data]);

  var byProjectRows = useMemo(function () {
    if (!data) return [];
    return data.by_project;
  }, [data]);

  var toolsData = useMemo(function () {
    if (!data) return null;
    return data.tools;
  }, [data]);

  var ctxBuckets = useMemo(function () {
    if (!data) return [];
    return data.context_histogram.buckets;
  }, [data]);

  var heatData = useMemo(function () {
    if (!data) return null;
    return data.heatmap;
  }, [data]);

  if (isLoading) return <p style={styles.msg}>Loading analytics…</p>;
  if (error) return <p style={styles.err}>Error: {String(error)}</p>;

  var kpis = data ? data.kpis : DEFAULT_KPIS;

  return (
    <div style={styles.page}>
      <h1 style={styles.heading}>Analytics</h1>
      <div style={styles.filterRow}>
        {RANGE_OPTIONS.map(function (opt) {
          return (
            <button
              key={opt.label}
              style={Object.assign({}, styles.filterBtn, days === opt.days ? styles.filterBtnActive : {})}
              onClick={function () { setDays(opt.days); }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      <KpiCards kpis={kpis} />
      <ThroughputChart bucketSize={bucketSize} buckets={throughputBuckets} />
      <TokenUsageChart bucketSize={bucketSize} buckets={tokenBuckets} />
      <div style={styles.tableRow}>
        <LeaderboardTable rows={byModelRows} />
        <PerProjectTable rows={byProjectRows} />
      </div>
      {toolsData && (
        <div style={styles.visualRow}>
          <ToolUsageBar tools={toolsData} />
          <ContextHistogram buckets={ctxBuckets} />
        </div>
      )}
      {heatData && (
        <ActivityHeatmap heatmap={heatData} />
      )}
    </div>
  );
}

var styles = {
  page: {
    padding: '1rem 1.5rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  heading: {
    margin: '0 0 1.25rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  msg: {
    padding: '1rem',
    color: T.colors.textDim,
    fontFamily: 'system-ui, sans-serif',
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
    marginBottom: '1.25rem',
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
    color: '#fff',
  } as React.CSSProperties,
  tableRow: {
    display: 'flex',
    gap: '1.5rem',
    flexWrap: 'wrap',
  } as React.CSSProperties,
  visualRow: {
    display: 'flex',
    gap: '1.5rem',
    flexWrap: 'wrap',
    marginBottom: '1rem',
  } as React.CSSProperties,
};
