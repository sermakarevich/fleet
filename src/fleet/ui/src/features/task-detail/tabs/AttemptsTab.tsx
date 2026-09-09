import { useState } from 'react';
import type { TaskAttempt } from '../../../shared/types';
import { formatClockTime, formatDuration } from '../../../shared/format';

// peak_context_pct from the API is already on the 0-100 scale (see
// state/task_summary.py::_build_attempts_summary), unlike shared/format.ts's
// formatPercent which expects a 0..1 fraction — so this stays local.
function formatAttemptContextPercent(percent: number | null): string {
  if (percent == null) return '—';
  return `${Math.round(percent)}%`;
}
import { useAttemptSummary, useAttemptPrompt } from '../../../shared/hooks/useApi';
import { merge, when } from '../../../shared/styles/recipes';
import * as T from '../../../shared/styles/tokens';

interface Props {
  taskId: string;
  attempts: TaskAttempt[];
}

// One row of the Attempts timeline: the fixed fields state/task_summary.py
// computes per attempt, plus an expandable derived summary and the recorded
// prompt.md fetched on demand (not embedded in the task payload).
export function AttemptsTab({ taskId, attempts }: Props) {
  const sorted = [...attempts].sort((a, b) => b.n - a.n);
  const [expanded, setExpanded] = useState<number | null>(null);

  if (sorted.length === 0) {
    return (
      <div style={styles.container}>
        <p style={styles.msg}>No attempts recorded yet.</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.list}>
        {sorted.map(a => (
          <AttemptRow
            key={a.n}
            taskId={taskId}
            attempt={a}
            isOpen={expanded === a.n}
            onToggle={() => setExpanded(expanded === a.n ? null : a.n)}
          />
        ))}
      </div>
    </div>
  );
}

function AttemptRow({
  taskId,
  attempt,
  isOpen,
  onToggle,
}: {
  taskId: string;
  attempt: TaskAttempt;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const summary = useAttemptSummary(taskId, attempt.n, isOpen && attempt.has_summary);
  const prompt = useAttemptPrompt(taskId, attempt.n, isOpen && attempt.has_prompt);

  return (
    <div style={styles.row}>
      <button
        style={merge(styles.header, when(attempt.kind === 'compact', styles.compactRow), when(attempt.outcome === 'waiting', styles.waitingRow), {  })}
        onClick={onToggle}
      >
        <span style={styles.chevron}>{isOpen ? '▾' : '▸'}</span>
        <span style={styles.cell}>#{attempt.n}</span>
        <span style={styles.cell}>
          {attempt.kind === 'compact' ? 'compaction' : (attempt.mode ?? '—')}
        </span>
        <span style={styles.cell}>{formatClockTime(attempt.started_at)}</span>
        <span style={styles.cell}>{formatDuration(attempt.duration_sec)}</span>
        <span style={styles.cell}>{[attempt.coder, attempt.model].filter(Boolean).join(' / ') || '—'}</span>
        <span style={styles.cell}>{attempt.outcome ?? '—'}</span>
        {attempt.context_badge && <span style={styles.contextBadge}>context</span>}
        <span style={styles.cell}>{formatAttemptContextPercent(attempt.peak_context_pct)}</span>
        <span style={styles.cell}>{attempt.files_touched} files</span>
        <span style={styles.cell}>{attempt.commits.length} commits</span>
        <span style={merge(styles.cell, styles.reasonCell)} title={attempt.reason ?? undefined}>
          {attempt.reason ?? '—'}
        </span>
      </button>
      {isOpen && (
        <div style={styles.details}>
          {attempt.result && (
            <div style={styles.detailBlock}>
              <div style={styles.detailLabel}>RESULT.json</div>
              <pre style={styles.pre}>{attempt.result.status}: {attempt.result.summary}</pre>
            </div>
          )}
          <div style={styles.detailBlock}>
            <div style={styles.detailLabel}>Summary (derived)</div>
            <pre style={styles.pre}>
              {!attempt.has_summary ? '(no summary for this attempt)' : summary.data?.content ?? 'Loading…'}
            </pre>
          </div>
          <div style={styles.detailBlock}>
            <div style={styles.detailLabel}>Prompt</div>
            <pre style={styles.pre}>
              {!attempt.has_prompt ? '(no recorded prompt for this attempt)' : prompt.data?.content ?? 'Loading…'}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    fontFamily: 'monospace',
    fontSize: '0.78rem',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.25rem 0.5rem',
  },
  row: {
    borderBottom: `1px solid ${T.colors.bgElevated}`,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.6rem',
    width: '100%',
    padding: '0.4rem 0.25rem',
    background: 'transparent',
    border: 'none',
    color: T.colors.textPrimary,
    cursor: 'pointer',
    textAlign: 'left',
    fontFamily: 'inherit',
    fontSize: 'inherit',
  },
  chevron: {
    color: T.colors.textDim,
    width: '0.8rem',
  },
  compactRow: {
    background: T.colors.bgWarm,
  },
  waitingRow: {
    background: T.colors.bgSurface,
    color: T.colors.textDim,
  },
  contextBadge: {
    whiteSpace: 'nowrap',
    fontSize: '0.68rem',
    fontWeight: 600,
    color: T.colors.clay,
    border: `1px solid ${T.colors.clayEdge}`,
    background: T.colors.clayWash,
    borderRadius: '4px',
    padding: '0 0.3rem',
  },
  cell: {
    whiteSpace: 'nowrap',
  },
  reasonCell: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    color: T.colors.textSecondary,
  },
  details: {
    padding: '0.5rem 1.5rem 1rem 1.5rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.6rem',
  },
  detailBlock: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.2rem',
  },
  detailLabel: {
    color: T.colors.textDim,
    fontWeight: 600,
  },
  pre: {
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    background: T.colors.bgDeeper,
    border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '4px',
    padding: '0.5rem',
    margin: 0,
    color: T.colors.textBody,
    maxHeight: '20rem',
    overflowY: 'auto',
  },
  msg: {
    padding: '0.5rem',
    color: T.colors.textDim,
    margin: 0,
  },
};
