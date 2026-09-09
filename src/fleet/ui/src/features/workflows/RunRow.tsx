/**
 * One workflow run as a table row (desktop) or a card (mobile): workflow
 * link, run number, trigger, timestamps, status chip and a per-step
 * progress bar. Called by RunsTable; row activation opens the run detail.
 */
import { Link } from 'react-router-dom';
import type { WorkflowRun } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { runStatusColor, statusLabel } from '../../shared/status';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { useClickableProps } from '../../shared/ui/Clickable';

// Segment color per step-run state (ADR 0008 vocabulary, never "job").
const STEP_SEGMENT: Record<string, string> = {
  done: '#16a34a',
  running: '#2563eb',
  attention: '#d97706',
  waiting: '#3f3f46',
};

// Small neutral chip for the run trigger (manual / cron).
export function TriggerChip({ trigger }: { trigger: string }) {
  return (
    <span style={R.merge(T.badge, styles.triggerChip)}>
      {trigger}
    </span>
  );
}

// "done/total" plus one slim segment per step, colored by step state.
export function RunProgress({ run }: { run: WorkflowRun }) {
  const steps = run.steps ?? [];
  const done = steps.filter((s) => s.state === 'done').length;
  return (
    <span style={styles.progress}>
      <span style={styles.progressCount}>
        {done}/{steps.length}
      </span>
      <span style={styles.bar} aria-label={`${done} of ${steps.length} steps done`}>
        {steps.map((s) => (
          <span
            key={s.step_name}
            title={`${s.step_name}: ${s.state}`}
            style={R.merge(styles.segment, {
              background: STEP_SEGMENT[s.state] ?? STEP_SEGMENT.waiting,
            })}
          />
        ))}
      </span>
    </span>
  );
}

// Colored run-status chip; shared with the workflow LastRunCell.
export function RunStatusChip({ status }: { status: string }) {
  const { bg, fg } = runStatusColor(status);
  return (
    <span style={R.merge(T.badge, { width: '6rem', flexShrink: 0, background: bg, color: fg })}>
      {statusLabel(status)}
    </span>
  );
}

interface Props {
  run: WorkflowRun;
  onOpen: (runId: string) => void;
}

// Desktop table row for one run; the inner workflow link must not open the run.
export function RunRow({ run, onOpen }: Props) {
  const rowClick = useClickableProps(() => onOpen(run.id));
  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <div style={R.rowStyle(false)} className="row-interactive" {...rowClick}>
      <span style={R.titleCellStyle()} title={run.workflow_name}>
        <Link to={`/workflows/${run.workflow_id}`} onClick={stop}>
          {run.workflow_name}
        </Link>
      </span>
      <span style={styles.nCol}>#{run.n}</span>
      <span style={styles.triggerCol}>
        <TriggerChip trigger={run.trigger} />
      </span>
      <span style={styles.tsCol}>{fmtTs(run.started_at)}</span>
      <span style={styles.tsCol}>{run.finished_at ? fmtTs(run.finished_at) : '—'}</span>
      <span style={styles.statusCol}>
        <RunStatusChip status={run.status} />
      </span>
      <span style={styles.progressCol}>
        <RunProgress run={run} />
      </span>
    </div>
  );
}

// Mobile card for one run.
export function RunCard({ run, onOpen }: Props) {
  const cardClick = useClickableProps(() => onOpen(run.id));
  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <div style={styles.card} className="row-interactive" {...cardClick}>
      <div style={styles.cardHead}>
        <span style={styles.cardName} title={run.workflow_name}>
          <Link to={`/workflows/${run.workflow_id}`} onClick={stop}>
            {run.workflow_name}
          </Link>{' '}
          #{run.n}
        </span>
        <RunStatusChip status={run.status} />
      </div>
      <div style={styles.cardMeta}>
        <TriggerChip trigger={run.trigger} />
        <span style={styles.cardMetaText}>
          {fmtTs(run.started_at)} → {run.finished_at ? fmtTs(run.finished_at) : '—'}
        </span>
      </div>
      <RunProgress run={run} />
    </div>
  );
}

const styles = {
  triggerChip: {
    width: '4.5rem', background: T.colors.bgSurface, color: T.colors.textSecondary,
    border: `1px solid ${T.colors.border}`,
  } as React.CSSProperties,
  nCol: {
    width: '3rem', flexShrink: 0, fontSize: '0.8125rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  triggerCol: { width: '5rem', flexShrink: 0 } as React.CSSProperties,
  tsCol: {
    width: '8rem', flexShrink: 0, fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  statusCol: { width: '6.5rem', flexShrink: 0 } as React.CSSProperties,
  progressCol: { flex: 1, minWidth: '8rem' } as React.CSSProperties,
  progress: {
    display: 'inline-flex', alignItems: 'center', gap: '0.5rem', width: '100%',
  } as React.CSSProperties,
  progressCount: {
    fontSize: '0.75rem', color: T.colors.textSecondary, flexShrink: 0,
  } as React.CSSProperties,
  bar: { display: 'inline-flex', gap: 2, flex: 1, minWidth: 0 } as React.CSSProperties,
  segment: { flex: 1, height: '0.375rem', borderRadius: 2, minWidth: 4 } as React.CSSProperties,
  card: {
    padding: '0.625rem 0.875rem', borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer', display: 'flex', flexDirection: 'column' as const,
    gap: '0.3rem', fontSize: '0.875rem', color: '#d4d4d8',
  } as React.CSSProperties,
  cardHead: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
  } as React.CSSProperties,
  cardName: {
    flex: 1, minWidth: 0, overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardMeta: {
    display: 'flex', gap: '0.625rem', flexWrap: 'wrap' as const, alignItems: 'center',
  } as React.CSSProperties,
  cardMetaText: {
    fontSize: '0.75rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
};
