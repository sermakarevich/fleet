import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ThroughputBucket } from '../../types';

const OUTCOME_COLORS: Record<string, string> = {
  success: '#22c55e',
  failure: '#ef4444',
  rate_limit: '#f59e0b',
  context_pressure: '#8b5cf6',
  blocked_by_agent: '#3b82f6',
};

function formatHour(iso: string): string {
  try {
    const d = new Date(iso);
    const day = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
    return `${String(d.getHours()).padStart(2, '0')}:00 ${day}`;
  } catch {
    return iso;
  }
}

interface Props {
  buckets: ThroughputBucket[];
}

export function ThroughputChart({ buckets }: Props) {
  const data = buckets.map(b => ({ ...b, label: formatHour(b.hour) }));

  if (data.length === 0) {
    return (
      <div style={styles.container}>
        <h3 style={styles.title}>Throughput (last 7 days)</h3>
        <p style={styles.empty}>No completed tasks in the past 7 days.</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>Throughput (last 7 days)</h3>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
          <XAxis dataKey="label" tick={{ fill: '#71717a', fontSize: 11 }} />
          <YAxis tick={{ fill: '#71717a', fontSize: 11 }} allowDecimals={false} />
          <Tooltip
            contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', fontSize: 12 }}
            labelStyle={{ color: '#e4e4e7' }}
            itemStyle={{ color: '#a1a1aa' }}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: '#a1a1aa' }} />
          {Object.entries(OUTCOME_COLORS).map(([key, color]) => (
            <Bar key={key} dataKey={key} stackId="a" fill={color} name={key.replace(/_/g, ' ')} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

const styles = {
  container: {
    marginBottom: '1.5rem',
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.75rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  empty: {
    color: '#52525b',
    fontSize: '0.875rem',
    margin: 0,
  } as React.CSSProperties,
};
