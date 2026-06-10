import { Link } from 'react-router-dom';
import type { TaskSummary } from '../types';

interface Props {
  tasks: TaskSummary[];
}

export function NeedsYouPanel({ tasks }: Props) {
  if (tasks.length === 0) {
    return (
      <section style={styles.section}>
        <h2 style={styles.title}>Needs you</h2>
        <p style={styles.empty}>All agents are unblocked</p>
      </section>
    );
  }

  return (
    <section style={styles.section}>
      <h2 style={styles.title}>Needs you ({tasks.length})</h2>
      {tasks.map(task => {
        const preview = task.last_event_detail ?? task.title;
        return (
          <Link key={task.id} to="/chat" style={styles.row}>
            <span style={styles.id}>{task.id}</span>
            <span style={styles.question}>{preview.slice(0, 120)}</span>
          </Link>
        );
      })}
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
    padding: '0.5rem 0.75rem',
    background: '#1c1c20',
    borderRadius: 4,
    textDecoration: 'none',
    color: 'inherit',
    marginBottom: '0.25rem',
    borderLeft: '3px solid #3b82f6',
  } as React.CSSProperties,
  id: {
    fontSize: '0.75rem',
    color: '#60a5fa',
    fontFamily: 'monospace',
    flexShrink: 0,
  } as React.CSSProperties,
  question: {
    fontSize: '0.875rem',
    color: '#e4e4e7',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
};
