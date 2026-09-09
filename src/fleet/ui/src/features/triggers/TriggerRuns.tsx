// Run-history rows for the trigger drawer, covering both targets: a
// past run links to the worker it opened (task schedules) or to the
// workflow run with its step progress (workflow schedules), or shows the
// skip reason. Rendered by TriggerDrawerBody.
import { Link } from 'react-router-dom';
import { useWorkflowRun } from '../../shared/hooks/useApi';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { StatusChip } from '../../shared/ui/StatusChip';
import type { ScheduleRun } from '../../shared/types';
import { RunProgress, RunStatusChip } from '../workflows/runColumns';

// Done/total step progress for one past workflow run, fetched lazily.
function WorkflowRunProgress({ workflowRunId }: { workflowRunId: string }) {
  const { data: run } = useWorkflowRun(workflowRunId);
  if (!run) return <span style={R.dimStyle()}>…</span>;
  return <RunProgress run={run} />;
}

// The run's outcome: worker link, workflow-run link with progress, or skip.
function RunOutcome({ run }: { run: ScheduleRun }) {
  if (run.skipped || (!run.task_id && !run.workflow_run_id)) {
    return <span style={R.dimStyle()}>skipped — {run.reason || 'no reason'}</span>;
  }
  if (run.workflow_run_id) {
    return (
      <span style={styles.runDetail}>
        <Link to={`/workflow-runs/${run.workflow_run_id}`} style={styles.runLink}>
          <RunStatusChip status={run.workflow_run_status ?? 'unknown'} />
        </Link>
        <WorkflowRunProgress workflowRunId={run.workflow_run_id} />
      </span>
    );
  }
  return (
    <Link to={`/workers/${run.task_id}`} style={styles.runLink}>
      <span style={R.monoStyle()}>{run.task_id}</span>
      <StatusChip status={run.task_status ?? 'unknown'} width="5rem" />
    </Link>
  );
}

// One past-run row: number, times, trigger and outcome.
export function TriggerRunRow({ run }: { run: ScheduleRun }) {
  return (
    <div style={styles.runRow}>
      <span style={styles.runN}>#{run.n}</span>
      <span style={styles.runTs} title={`fired ${run.fired_at}`}>{fmtTs(run.scheduled_for)}</span>
      <span style={R.miniChipStyle(run.trigger)}>{run.trigger}</span>
      <RunOutcome run={run} />
    </div>
  );
}

// Past runs section: shared by both targets (rows branch internally).
export function TriggerRuns({ runs }: { runs: ScheduleRun[] }) {
  if (runs.length === 0) return <p style={R.dimStyle()}>No runs yet.</p>;
  return (
    <>
      {runs.map((run) => (
        <TriggerRunRow key={run.n} run={run} />
      ))}
    </>
  );
}

const styles = {
  runRow: {
    display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.375rem 0',
    borderBottom: `1px solid ${T.colors.borderSubtle}`, fontSize: '0.8125rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  runN: {
    fontFamily: 'monospace', color: T.colors.textSecondary,
    width: '2.5rem', flexShrink: 0,
  } as React.CSSProperties,
  runTs: { color: T.colors.textBody, flexShrink: 0 } as React.CSSProperties,
  runDetail: {
    display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
    flex: 1, minWidth: '10rem',
  } as React.CSSProperties,
  runLink: {
    display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
    color: T.colors.link, textDecoration: 'none', fontSize: '0.8125rem',
  } as React.CSSProperties,
};
