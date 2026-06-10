import type { RuntimeConfig, TaskDetail } from '../../types';
import * as T from '../../styles/tokens';

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

function fmtTs(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const now = new Date();
  const pad = (n: number) => n.toString().padStart(2, '0');
  const t = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return t;
  const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()];
  return `${mo} ${d.getDate()} ${t}`;
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
        <span style={styles.metaItem}>started: {fmtTs(task.started_at)}</span>
        {task.ended_at && (
          <>
            <span style={styles.metaSep}>·</span>
            <span style={styles.metaItem}>ended: {fmtTs(task.ended_at)}</span>
          </>
        )}
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
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    background: T.colors.bgSurface,
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
    color: T.colors.textPrimary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  meta: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.25rem',
    fontSize: '0.75rem',
    color: T.colors.textDim,
  },
  coderModel: {
    fontFamily: 'monospace',
    fontSize: '0.75rem',
  },
  bold: {
    color: T.colors.textPrimary,
    fontWeight: 700,
  },
  dim: {
    color: T.colors.textMuted,
    fontStyle: 'italic',
  },
  sep: {
    color: T.colors.border,
    margin: '0 0.1rem',
  },
  metaSep: {
    color: T.colors.border,
  },
  metaItem: {
    color: T.colors.textDim,
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
