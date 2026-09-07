import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import * as P from '../chartTheme';
import { bucketTickLabel, bucketTooltipLabel } from '../timeBuckets';

// Stack order keeps amber between green and red so adjacent segments stay
// separable under CVD (validated); failed ends up on top where it pops.
const SERIES: { key: 'success' | 'blocked' | 'failed'; name: string; color: string }[] = [
  { key: 'success', name: 'Success', color: P.seriesColors.success },
  { key: 'blocked', name: 'Blocked', color: P.seriesColors.blocked },
  { key: 'failed', name: 'Failed', color: P.seriesColors.failed },
];

interface Props {
  bucketSize: 'hour' | 'day';
  buckets: { bucket: string; success: number; failed: number; blocked: number }[];
}

export function ThroughputChart({ bucketSize, buckets }: Props) {
  const total = buckets.reduce((s, b) => s + b.success + b.failed + b.blocked, 0);

  return (
    <div style={P.panel}>
      <div style={P.panelTitle}>
        <span>Throughput</span>
        <span style={P.panelTitleAside}>
          {total > 0 ? `${total} completed / ${bucketSize}` : ''}
        </span>
      </div>
      {buckets.length === 0 ? (
        <p style={P.panelEmpty}>No completed tasks in this window.</p>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={buckets} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={P.chartGridStroke} vertical={false} />
            <XAxis
              dataKey="bucket"
              tick={P.chartAxisTick}
              tickLine={false}
              axisLine={{ stroke: P.chartGridStroke }}
              tickFormatter={(iso: string) => bucketTickLabel(bucketSize, iso)}
              minTickGap={24}
            />
            <YAxis
              tick={P.chartAxisTick}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
              width={36}
            />
            <Tooltip
              {...P.chartTooltipProps}
              labelFormatter={(iso: string) => bucketTooltipLabel(bucketSize, iso)}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" iconSize={8} />
            {SERIES.map(s => (
              <Bar
                key={s.key}
                dataKey={s.key}
                stackId="a"
                fill={s.color}
                name={s.name}
                stroke="#1c1c20"
                strokeWidth={1}
                maxBarSize={40}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
