import { useState } from 'react';
import type { RuntimeConfig, TaskDetail } from '../../shared/types';
import * as T from '../../shared/styles/tokens';
import { useUnblockTask } from '../../shared/hooks/useApi';
import { statusColor, statusLabel } from '../../shared/status';
import { formatTimestamp, formatTokens, formatContextTitle } from '../../shared/format';
import { merge } from '../../shared/styles/recipes';

interface Props {
  task: TaskDetail;
  config: RuntimeConfig | undefined;
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

export function TaskDetailHeader({ task, config }: Props) {
  const [descExpanded, setDescExpanded] = useState(false);
  const desc = task.description;
  const descLong = typeof desc === 'string' && desc.length > 400;
  const descVisible = descExpanded || !descLong;
  const unblockTask = useUnblockTask();
  const isBlocked = task.status === 'blocked';

  const rounds = task.rounds ?? { failure: 0, stall: 0, context: 0, partial: 0, noclose: 0 };
  const counters: string[] = [];
  if (rounds.failure) counters.push(`${rounds.failure} failures`);
  if (rounds.noclose) counters.push(`${rounds.noclose} no-close`);
  if (rounds.stall) counters.push(`${rounds.stall} stalls`);
  if (rounds.partial) counters.push(`${rounds.partial} partial`);
  if (rounds.context) counters.push(`${rounds.context} context`);
  if (task.restarts) counters.push(`${task.restarts} restarts`);

  return (
    <div style={styles.header}>
      <div style={styles.row}>
        <span style={styles.id}>{task.id}</span>
        <span
          style={merge(styles.pill, { background: statusColor(task.status).bg, color: statusColor(task.status).fg,  })}
        >
          {statusLabel(task.status)}
        </span>
        <span style={styles.title}>{task.title}</span>
        {task.job_phase && (
          <span style={styles.jobPill} title={`job phase (worker: job.${task.job_phase})`}>
            job: {task.job_phase}
          </span>
        )}
      </div>
      {isBlocked && (
        <div style={styles.blockedBanner}>
          <span style={styles.blockedLabel}>Blocked</span>
          <span style={styles.blockedText}>{task.blocked_reason ?? 'No recorded reason'}</span>
          <span style={styles.metaSep}>·</span>
          <span style={styles.metaItem}>{formatTimestamp(task.blocked_at)}</span>
          {counters.length > 0 && (
            <>
              <span style={styles.metaSep}>·</span>
              <span style={styles.metaItem}>{counters.join(' · ')}</span>
            </>
          )}
          <button
            style={styles.unblockBtn}
            onClick={() => unblockTask.mutate({ id: task.id })}
          >
            Unblock
          </button>
        </div>
      )}
      {desc && (
        <div style={styles.descContainer}>
          <span
            style={merge(styles.desc, { maxHeight: descVisible ? 'none' : `${12 * 16}px`, overflow: 'hidden',  })}
          >
            {desc}
          </span>
          {descLong && (
            <button
              style={styles.descToggle}
              onClick={() => setDescExpanded(!descExpanded)}
            >
              {descExpanded ? 'show less' : 'show more'}
            </button>
          )}
        </div>
      )}
      <div style={styles.meta}>
        <CoderModel task={task} config={config} />
        <span style={styles.metaSep}>·</span>
        <span style={styles.metaItem} title={formatContextTitle(task.context_tokens, task.context_limit)}>
          ctx: {formatTokens(task.context_tokens, task.context_pct)}
        </span>
        <span style={styles.metaSep}>·</span>
        <span style={styles.metaItem}>started: {formatTimestamp(task.started_at)}</span>
        {task.ended_at && (
          <>
            <span style={styles.metaSep}>·</span>
            <span style={styles.metaItem}>ended: {formatTimestamp(task.ended_at)}</span>
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
    color: T.colors.link,
    flexShrink: 0,
  },
  pill: {
    display: 'inline-block',
    padding: '0.1rem 0.45rem',
    borderRadius: 9999,
    fontSize: '0.7rem',
    fontWeight: 600,
    color: T.colors.white,
    flexShrink: 0,
  },
  jobPill: {
    display: 'inline-block',
    padding: '0.1rem 0.45rem',
    borderRadius: 9999,
    fontSize: '0.7rem',
    fontWeight: 600,
    color: T.colors.lavender,
    border: '1px solid #a78bfa',
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
    color: T.colors.link,
    textDecoration: 'none',
    fontFamily: 'monospace',
    maxWidth: 300,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  descContainer: {
    marginTop: '0.35rem',
  },
  desc: {
    fontSize: '0.8rem',
    color: T.colors.textMuted,
    whiteSpace: 'pre-wrap',
    display: 'block',
  },
  descToggle: {
    fontSize: '0.75rem',
    color: T.colors.link,
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    padding: '0.15rem 0',
    fontFamily: 'inherit',
    marginTop: '0.1rem',
  },
  blockedBanner: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.4rem',
    padding: '0.35rem 0.5rem',
    marginBottom: '0.35rem',
    background: 'rgba(245, 158, 11, 0.1)',
    border: '1px solid #f59e0b',
    borderRadius: 4,
    fontSize: '0.8rem',
  },
  blockedLabel: {
    fontWeight: 700,
    color: T.colors.amber,
    flexShrink: 0,
  },
  blockedText: {
    color: T.colors.textPrimary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
    minWidth: 0,
  },
  unblockBtn: {
    padding: '0.15rem 0.5rem',
    background: 'transparent',
    border: '1px solid #f59e0b',
    borderRadius: 4,
    color: T.colors.amber,
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
    fontWeight: 600,
    flexShrink: 0,
  },
};
