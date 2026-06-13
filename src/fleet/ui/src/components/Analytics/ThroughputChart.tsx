import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const OUTCOME_COLORS: Record<string, string> = {
  success: '#22c55e',
  failed: '#ef4444',
  blocked: '#d97706',
};

interface Props {
  bucketSize: 'hour' | 'day';
  buckets: { bucket: string; success: number; failed: number; blocked: number }[];
}

function formatBucketLabel(bucketSize: string, iso: string): string {
  try {
    const d = new Date(iso);
    if (bucketSize === 'hour') {
      return `${String(d.getHours()).padStart(2, '0')}:00`;
    }
    // day bucket: "Mon DD" format
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}

export function ThroughputChart({ bucketSize, buckets }: Props) {
  const data = buckets.map(b => ({ ...b, label: formatBucketLabel(bucketSize, b.bucket) }));

  if (data.length === 0) {
    return (
      <div style={styles.container}>
        <h3 style={styles.title}>Throughput</h3>
        <p style={styles.empty}>No completed tasks in this window.</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>Throughput</h3>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
          <XAxis
            dataKey="label"
            tick={{ fill: '#71717a', fontSize: 11 }}
            interval={data.length > 24 ? 3 : 0}
          />
          <YAxis tick={{ fill: '#71717a', fontSize: 11 }} allowDecimals={false} />
          <Tooltip
            contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', fontSize: 12 }}
            labelStyle={{ color: '#e4e4e7' }}
            itemStyle={{ color: '#a1a1aa' }}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: '#a1a1aa' }} />
          {Object.entries(OUTCOME_COLORS).map(([key, color]) => (
            <Bar key={key} dataKey={key} stackId="a" fill={color} name={key.charAt(0).toUpperCase() + key.slice(1)} />
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
