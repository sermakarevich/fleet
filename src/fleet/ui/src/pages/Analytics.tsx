import { useAnalytics } from '../hooks/useApi';
import { ThroughputChart } from '../components/Analytics/ThroughputChart';
import { LeaderboardTable } from '../components/Analytics/LeaderboardTable';
import { RateLimitTimeline } from '../components/Analytics/RateLimitTimeline';
import { PerProjectTable } from '../components/Analytics/PerProjectTable';
import type { BurnoutRow, LeaderboardRow, PerProjectRow, RateLimitEvent, ThroughputBucket } from '../types';

export function Analytics() {
  const { throughput, leaderboard, burnouts, rateLimits, perProject, loading } = useAnalytics();

  if (loading) return <p style={styles.msg}>Loading analytics…</p>;

  return (
    <div style={styles.page}>
      <h1 style={styles.heading}>Analytics</h1>
      <ThroughputChart
        buckets={(throughput as { buckets: ThroughputBucket[] } | undefined)?.buckets ?? []}
      />
      <LeaderboardTable
        rows={(leaderboard as { rows: LeaderboardRow[] } | undefined)?.rows ?? []}
      />
      <RateLimitTimeline
        burnouts={(burnouts as { rows: BurnoutRow[] } | undefined)?.rows ?? []}
        rateLimits={(rateLimits as { events: RateLimitEvent[] } | undefined)?.events ?? []}
      />
      <PerProjectTable
        rows={(perProject as { rows: PerProjectRow[] } | undefined)?.rows ?? []}
      />
    </div>
  );
}

const styles = {
  page: {
    padding: '1rem 1.5rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  heading: {
    margin: '0 0 1.25rem',
    fontSize: '1rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  msg: {
    padding: '1rem',
    color: '#71717a',
  } as React.CSSProperties,
};
