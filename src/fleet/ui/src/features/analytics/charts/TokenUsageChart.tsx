import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import * as P from '../chartTheme';
import { bucketTickLabel, bucketTooltipLabel } from '../timeBuckets';
import { formatTokens } from '../../../shared/format';
import * as T from '../../../shared/styles/tokens';

interface Props {
  bucketSize: 'hour' | 'day';
  buckets: { bucket: string; output_tokens: number; input_tokens: number; cache_tokens: number }[];
}

// Cache traffic runs 3–4 orders of magnitude above fresh input/output, so a
// single axis would flatten the interesting series to zero. Two small
// multiples share the x-axis instead — never a second y-axis.
export function TokenUsageChart({ bucketSize, buckets }: Props) {
  const hasData = buckets.some(b => b.output_tokens + b.input_tokens + b.cache_tokens > 0);

  const shared = {
    margin: { top: 4, right: 8, left: 0, bottom: 0 },
  };
  const yAxis = (
    <YAxis
      tick={P.chartAxisTick}
      tickLine={false}
      axisLine={false}
      tickFormatter={(v: number) => formatTokens(v)}
      width={56}
    />
  );
  const tooltip = (
    <Tooltip
      {...P.chartTooltipProps}
      labelFormatter={(iso: string) => bucketTooltipLabel(bucketSize, iso)}
      formatter={(value: number) => formatTokens(value)}
    />
  );

  return (
    <div style={P.panel}>
      <div style={P.panelTitle}>
        <span>Token usage</span>
      </div>
      {!hasData ? (
        <p style={P.panelEmpty}>No token usage in this window.</p>
      ) : (
        <>
          <div style={subLabel}>Input + output</div>
          <ResponsiveContainer width="100%" height={130}>
            <BarChart data={buckets} {...shared} syncId="tokens">
              <CartesianGrid strokeDasharray="3 3" stroke={P.chartGridStroke} vertical={false} />
              <XAxis dataKey="bucket" hide />
              {yAxis}
              {tooltip}
              <Legend
                wrapperStyle={{ fontSize: 12 }}
                iconType="circle"
                iconSize={8}
                verticalAlign="top"
                align="right"
                height={20}
              />
              <Bar
                dataKey="input_tokens"
                stackId="fresh"
                fill={P.seriesColors.input}
                name="Input"
                stroke={T.colors.bgElevated}
                strokeWidth={1}
                maxBarSize={40}
                isAnimationActive={false}
              />
              <Bar
                dataKey="output_tokens"
                stackId="fresh"
                fill={P.seriesColors.output}
                name="Output"
                stroke={T.colors.bgElevated}
                strokeWidth={1}
                maxBarSize={40}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
          <div style={subLabel}>Cache read + write</div>
          <ResponsiveContainer width="100%" height={130}>
            <BarChart data={buckets} {...shared} syncId="tokens">
              <CartesianGrid strokeDasharray="3 3" stroke={P.chartGridStroke} vertical={false} />
              <XAxis
                dataKey="bucket"
                tick={P.chartAxisTick}
                tickLine={false}
                axisLine={{ stroke: P.chartGridStroke }}
                tickFormatter={(iso: string) => bucketTickLabel(bucketSize, iso)}
                minTickGap={24}
              />
              {yAxis}
              {tooltip}
              <Bar
                dataKey="cache_tokens"
                fill={P.seriesColors.cache}
                name="Cache"
                maxBarSize={40}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  );
}

const subLabel: React.CSSProperties = {
  fontSize: '0.6875rem',
  color: T.colors.textDim,
  margin: '0.25rem 0 0.125rem 0.25rem',
};
