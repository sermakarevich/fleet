import { Link } from 'react-router-dom';
import type { TaskSummary } from '../types';

function outcomeStyle(task: TaskSummary): React.CSSProperties {
  switch (task.last_event_kind) {
    case 'result':
      return { borderLeft: '3px solid #22c55e', background: '#052e16' };
    case 'error':
      return { borderLeft: '3px solid #ef4444', background: '#450a0a' };
    case 'rate_limit':
      return { borderLeft: '3px solid #f97316', background: '#431407' };
    case 'context_pressure':
      return { borderLeft: '3px solid #eab308', background: '#422006' };
    default:
      if (task.status === 'blocked') {
        return { borderLeft: '3px solid #3b82f6', background: '#0f1629' };
      }
      return { borderLeft: '3px solid #52525b', background: '#18181b' };
  }
}

interface Props {
  tasks: TaskSummary[];
}

export function RecentOutcomes({ tasks }: Props) {
  if (tasks.length === 0) {
    return (
      <section style={styles.section}>
        <h2 style={styles.title}>Recent outcomes</h2>
        <p style={styles.empty}>No completed tasks</p>
      </section>
    );
  }

  return (
    <section style={styles.section}>
      <h2 style={styles.title}>Recent outcomes ({tasks.length})</h2>
      {tasks.map(task => (
        <Link key={task.id} to={`/tasks/${task.id}`} style={{ ...styles.row, ...outcomeStyle(task) }}>
          <span style={styles.id}>{task.id}</span>
          <span style={styles.outcome}>{task.last_event_kind ?? '—'}</span>
          <span style={styles.title2}>{(task.title ?? '').slice(0, 60)}</span>
        </Link>
      ))}
    </section>
  );
}

const styles = {
  section: {
    marginBottom: '1.5rem',
  } as React.CSSProperties,
  title: {
    fontSize: '0.75rem',
    fontWeight: 600,
    color: '#71717a',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: '0.5rem',
  } as React.CSSProperties,
  empty: {
    color: '#52525b',
    fontSize: '0.875rem',
    margin: 0,
  } as React.CSSProperties,
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    padding: '0.4rem 0.75rem',
    borderRadius: 4,
    textDecoration: 'none',
    color: 'inherit',
    marginBottom: '0.2rem',
  } as React.CSSProperties,
  id: {
    fontSize: '0.75rem',
    color: '#a1a1aa',
    fontFamily: 'monospace',
    flexShrink: 0,
  } as React.CSSProperties,
  outcome: {
    fontSize: '0.75rem',
    color: '#d4d4d8',
    flexShrink: 0,
    width: '6rem',
  } as React.CSSProperties,
  title2: {
    fontSize: '0.875rem',
    color: '#e4e4e7',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
};
