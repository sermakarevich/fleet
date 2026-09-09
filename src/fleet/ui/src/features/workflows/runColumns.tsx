// Per-run cell renderers for the shared DataList: desktop column
// definitions plus the mobile card body. Trigger chip, step progress
// bar and status chip stay pure renderers. Rendered by WorkflowsPage
// (all-runs and per-workflow views) via DataList; activation opens
// the run detail page.
import { Link } from 'react-router-dom';
import type { WorkflowRun } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { runStatusColor, statusLabel } from '../../shared/status';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import type { DataColumn } from '../../shared/ui/DataList';

// Segment color per step-run state (ADR 0008 vocabulary, never "job").
const STEP_SEGMENT: Record<string, string> = {
  done: T.colors.tickGreen,
  running: T.colors.info,
  attention: T.colors.amberDark,
  waiting: T.colors.border,
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

// Workflow name cell linking to the definition (must not open the run).
export function RunWorkflowCell({ run }: { run: WorkflowRun }) {
  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <span style={R.titleCellStyle()} title={run.workflow_name}>
      <Link to={`/workflows/${run.workflow_id}`} onClick={stop}>
        {run.workflow_name}
      </Link>
    </span>
  );
}

// Desktop columns for the runs DataList.
export function runColumns(): Array<DataColumn<WorkflowRun>> {
  return [
    { key: 'workflow', header: 'Workflow', render: (run) => <RunWorkflowCell run={run} /> },
    {
      key: 'n', header: '#', width: '3rem',
      render: (run) => <span style={styles.nCol}>#{run.n}</span>,
    },
    {
      key: 'trigger', header: 'Trigger', width: '5rem',
      render: (run) => <TriggerChip trigger={run.trigger} />,
    },
    {
      key: 'started', header: 'Started', width: '8rem',
      render: (run) => <span style={styles.tsCol}>{fmtTs(run.started_at)}</span>,
    },
    {
      key: 'finished', header: 'Finished', width: '8rem',
      render: (run) => <span style={styles.tsCol}>{run.finished_at ? fmtTs(run.finished_at) : '—'}</span>,
    },
    {
      key: 'status', header: 'Status', width: '6.5rem',
      render: (run) => <RunStatusChip status={run.status} />,
    },
    {
      key: 'progress', header: 'Progress',
      render: (run) => <RunProgress run={run} />,
    },
  ];
}

// Mobile card body for one run.
export function RunCard({ run }: { run: WorkflowRun }) {
  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <>
      <div style={R.cardHeadStyle()}>
        <span style={R.cardTitleStyle()} title={run.workflow_name}>
          <Link to={`/workflows/${run.workflow_id}`} onClick={stop}>
            {run.workflow_name}
          </Link>{' '}
          #{run.n}
        </span>
        <RunStatusChip status={run.status} />
      </div>
      <div style={R.cardMetaStyle()}>
        <TriggerChip trigger={run.trigger} />
        <span style={R.cardMetaTextStyle()}>
          {fmtTs(run.started_at)} → {run.finished_at ? fmtTs(run.finished_at) : '—'}
        </span>
      </div>
      <RunProgress run={run} />
    </>
  );
}

const styles = {
  triggerChip: {
    width: '4.5rem', background: T.colors.bgSurface, color: T.colors.textSecondary,
    border: `1px solid ${T.colors.border}`,
  } as React.CSSProperties,
  nCol: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  tsCol: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  progress: {
    display: 'inline-flex', alignItems: 'center', gap: '0.5rem', width: '100%',
  } as React.CSSProperties,
  progressCount: {
    fontSize: '0.75rem', color: T.colors.textSecondary, flexShrink: 0,
  } as React.CSSProperties,
  bar: { display: 'inline-flex', gap: '0.125rem', flex: 1, minWidth: 0 } as React.CSSProperties,
  segment: { flex: 1, height: '0.375rem', borderRadius: '0.125rem', minWidth: '0.25rem' } as React.CSSProperties,
};
