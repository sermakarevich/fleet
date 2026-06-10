import { useEffect } from 'react';
import { NeedsYouPanel } from '../components/NeedsYouPanel';
import { RecentOutcomes } from '../components/RecentOutcomes';
import { RunningTable } from '../components/RunningTable';
import { useTasksState } from '../hooks/useTasksState';
import { useWebSocket } from '../hooks/useWebSocket';
import { useConfig, useTasks } from '../hooks/useApi';
import type { TaskSummary } from '../types';

export function Dashboard() {
  const { data: polledTasks, isLoading, error } = useTasks();
  const { data: config } = useConfig();
  const thresholdPct = config?.context_pressure_threshold_pct ?? 90;

  const { tasks, setTasks, updateFromEvent } = useTasksState([]);

  useEffect(() => {
    if (polledTasks) setTasks(polledTasks);
  }, [polledTasks, setTasks]);

  useWebSocket(updateFromEvent);

  const blocked: TaskSummary[] = tasks.filter(t => t.status === 'blocked');
  const running: TaskSummary[] = tasks.filter(t => t.status === 'in_progress');
  const closed: TaskSummary[] = tasks.filter(t => t.status === 'closed').slice(-20);

  if (isLoading && tasks.length === 0) {
    return <p style={styles.msg}>Loading…</p>;
  }

  if (error && tasks.length === 0) {
    return <p style={{ ...styles.msg, color: '#ef4444' }}>Error: {String(error)}</p>;
  }

  return (
    <div style={styles.page}>
      <NeedsYouPanel tasks={blocked} />
      <RunningTable tasks={running} thresholdPct={thresholdPct} />
      <RecentOutcomes tasks={closed} />
    </div>
  );
}

const styles = {
  page: {
    padding: '1rem 1.5rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  msg: {
    padding: '1rem',
    color: '#71717a',
  } as React.CSSProperties,
};
