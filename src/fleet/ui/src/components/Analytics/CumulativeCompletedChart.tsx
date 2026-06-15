import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

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
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}

export function CumulativeCompletedChart({ bucketSize, buckets }: Props) {
  let running = 0;
  const data = buckets.map(b => {
    running += (b.success || 0) + (b.failed || 0) + (b.blocked || 0);
    return { label: formatBucketLabel(bucketSize, b.bucket), cumulative: running };
  });

  if (data.length === 0) {
    return (
      <div style={styles.container}>
        <h3 style={styles.title}>Cumulative completed</h3>
        <p style={styles.empty}>No completed tasks in this window.</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>Cumulative completed</h3>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
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
          <Line type="monotone" dataKey="cumulative" stroke="#22c55e" strokeWidth={2} dot={false} name="Cumulative" />
        </LineChart>
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
