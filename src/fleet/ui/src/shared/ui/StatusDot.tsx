import type { TaskSummary } from '../types';
import { merge } from '../styles/recipes';
import * as T from '../styles/tokens';

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
  green: T.colors.success,
  amber: T.colors.amber,
  red: T.colors.danger,
  gray: T.colors.textMuted,
};

export type DotColor = keyof typeof DOT_COLORS;

/** Bare status circle; StatusDot and NavBar's connection dot build on it. */
export function Dot({ color, title }: { color: DotColor; title?: string }) {
  return (
    <span
      title={title}
      style={merge(styles.dot, { background: DOT_COLORS[color] })}
    />
  );
}

interface Props {
  task: TaskSummary;
  thresholdPct?: number;
}

export function StatusDot({ task, thresholdPct = 90 }: Props) {
  const color = getStatusDotColor(task, thresholdPct);
  const idle = (task.idle_sec ?? 0).toFixed(0);
  const ctx = (task.context_pct ?? 0).toFixed(1);
  return <Dot color={color} title={`${color}: idle ${idle}s, ctx ${ctx}%`} />;
}

const styles = {
  dot: {
    display: 'inline-block', width: 8, height: 8,
    borderRadius: '50%', flexShrink: 0,
  } as React.CSSProperties,
};
