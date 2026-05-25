import type { TaskSummary } from '../types';

export function getStatusDotColor(
  task: TaskSummary,
  thresholdPct: number,
): 'green' | 'amber' | 'red' {
  if (
    task.last_event_kind === 'rate_limit' ||
    (task.context_pct != null && task.context_pct >= 0.8 * thresholdPct)
  ) {
    return 'red';
  }
  if (task.idle_sec != null && task.idle_sec >= 60) {
    return 'amber';
  }
  return 'green';
}

const DOT_COLORS: Record<string, string> = {
  green: '#22c55e',
  amber: '#f59e0b',
  red: '#ef4444',
};

interface Props {
  task: TaskSummary;
  thresholdPct?: number;
}

export function StatusDot({ task, thresholdPct = 90 }: Props) {
  const color = getStatusDotColor(task, thresholdPct);
  const idle = (task.idle_sec ?? 0).toFixed(0);
  const ctx = (task.context_pct ?? 0).toFixed(1);
  return (
    <span
      title={`${color}: idle ${idle}s, ctx ${ctx}%`}
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: DOT_COLORS[color],
        flexShrink: 0,
      }}
    />
  );
}
