import type { RuntimeConfig, TaskDetail } from '../../types';

interface Props {
  task: TaskDetail;
  config: RuntimeConfig | undefined;
}

function statusColor(status: string): string {
  switch (status) {
    case 'in_progress': return '#3b82f6';
    case 'blocked': return '#f59e0b';
    case 'closed': return '#22c55e';
    case 'failed': return '#ef4444';
    default: return '#71717a';
  }
}

function fmtElapsed(sec: number | null): string {
  if (sec == null) return '—';
  if (sec < 60) return `${Math.floor(sec)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.floor(sec % 60)}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

function CoderModel({ task, config }: { task: TaskDetail; config: RuntimeConfig | undefined }) {
  const coder = task.coder;
  const model = task.model;
  const defaultCoder = config?.coder ?? '—';
  const defaultModel = config?.model ?? '—';

  return (
    <span style={styles.coderModel}>
      <span style={coder ? styles.bold : styles.dim}>
        {coder ?? `(default: ${defaultCoder})`}
      </span>
      <span style={styles.sep}>/</span>
      <span style={model ? styles.bold : styles.dim}>
        {model ?? `(default: ${defaultModel})`}
      </span>
    </span>
  );
}

export function Header({ task, config }: Props) {
  return (
    <div style={styles.header}>
      <div style={styles.row}>
        <span style={styles.id}>{task.id}</span>
        <span
          style={{
            ...styles.pill,
            background: statusColor(task.status),
          }}
        >
          {task.status}
        </span>
        <span style={styles.title}>{task.title}</span>
      </div>
      <div style={styles.meta}>
        <CoderModel task={task} config={config} />
        <span style={styles.metaSep}>·</span>
        <span style={styles.metaItem}>elapsed: {fmtElapsed(task.elapsed_sec)}</span>
        {task.cwd && (
          <>
            <span style={styles.metaSep}>·</span>
            <a
              href={`vscode://file/${task.cwd}`}
              style={styles.link}
              title="Open in VS Code"
            >
              {task.cwd}
            </a>
          </>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    padding: '0.75rem 1rem',
    borderBottom: '1px solid #27272a',
    background: '#18181b',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginBottom: '0.25rem',
  },
  id: {
    fontFamily: 'monospace',
    fontSize: '0.8rem',
    color: '#60a5fa',
    flexShrink: 0,
  },
  pill: {
    display: 'inline-block',
    padding: '0.1rem 0.45rem',
    borderRadius: 9999,
    fontSize: '0.7rem',
    fontWeight: 600,
    color: '#fff',
    flexShrink: 0,
  },
  title: {
    fontSize: '0.95rem',
    fontWeight: 600,
    color: '#e4e4e7',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  meta: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.25rem',
    fontSize: '0.75rem',
    color: '#71717a',
  },
  coderModel: {
    fontFamily: 'monospace',
    fontSize: '0.75rem',
  },
  bold: {
    color: '#e4e4e7',
    fontWeight: 700,
  },
  dim: {
    color: '#52525b',
    fontStyle: 'italic',
  },
  sep: {
    color: '#3f3f46',
    margin: '0 0.1rem',
  },
  metaSep: {
    color: '#3f3f46',
  },
  metaItem: {
    color: '#71717a',
  },
  link: {
    color: '#60a5fa',
    textDecoration: 'none',
    fontFamily: 'monospace',
    maxWidth: 300,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
};
