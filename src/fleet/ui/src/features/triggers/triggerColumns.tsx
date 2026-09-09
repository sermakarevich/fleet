// Per-trigger cell renderers for the shared DataList, parameterised by
// target: desktop column definitions plus the mobile card body. Workflow
// names resolve in TriggerTable (via useWorkflows) and pass in as a plain
// lookup so the cells stay pure. Rendered by TriggerTable via DataList.
import { Link } from 'react-router-dom';
import type { Schedule } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { StatusChip } from '../../shared/ui/StatusChip';
import type { DataColumn } from '../../shared/ui/DataList';
import { RunStatusChip } from '../workflows/runColumns';
import type { TriggerTarget } from './types';

// Green when enabled, dim gray when disabled.
export function EnabledDot({ enabled }: { enabled: boolean }) {
  return (
    <span
      title={enabled ? 'enabled' : 'disabled'}
      style={R.merge(styles.dot, enabled ? styles.dotOn : styles.dotOff)}
    />
  );
}

// Clicking a link inside a row must not select the row.
function stop(e: React.MouseEvent) {
  e.stopPropagation();
}

// Target detail: coder·model for a task schedule, workflow link for a
// workflow schedule.
export function TargetDetailCell({
  schedule, target, workflowName,
}: {
  schedule: Schedule; target: TriggerTarget; workflowName: string | null;
}) {
  if (target === 'workflow') {
    if (!schedule.workflow_id) return <span style={R.dimStyle()}>—</span>;
    return (
      <Link
        to={`/workflows/${schedule.workflow_id}`}
        onClick={stop}
        style={styles.link}
        title={schedule.workflow_id}
      >
        {workflowName ?? schedule.workflow_id}
      </Link>
    );
  }
  const coder = schedule.coder ?? '—';
  const model = schedule.model ? `·${schedule.model}` : '';
  return (
    <span style={styles.detailCell} title={`${schedule.coder ?? '—'} / ${schedule.model ?? '—'}`}>
      {coder}{model}
    </span>
  );
}

// Last-run cell: status chip linking to the worker or the workflow run,
// "skipped", or "never".
export function TriggerLastRunCell({ schedule }: { schedule: Schedule }) {
  const last = schedule.last_run;
  if (!last) return <span style={R.dimStyle()}>never</span>;
  if (last.skipped) return <span style={R.dimStyle()}>skipped</span>;
  if (last.workflow_run_id) {
    return (
      <Link to={`/workflow-runs/${last.workflow_run_id}`} onClick={stop} style={styles.runLink}>
        <RunStatusChip status={last.workflow_run_status ?? 'unknown'} />
      </Link>
    );
  }
  if (!last.task_id) return <span style={R.dimStyle()}>skipped — {last.reason || 'no reason'}</span>;
  return (
    <Link to={`/workers/${last.task_id}`} onClick={stop} style={styles.runLink}>
      <StatusChip status={last.task_status ?? 'unknown'} width="6rem" />
    </Link>
  );
}

// Desktop columns for the trigger DataList. Overlap shows for workflow
// schedules only (task schedules always render skip/queue the same way,
// so the column would be noise there).
export function triggerColumns(
  target: TriggerTarget,
  workflowNames: Record<string, string>,
): Array<DataColumn<Schedule>> {
  const cols: Array<DataColumn<Schedule>> = [
    {
      key: 'enabled', header: 'Enabled', width: '4rem',
      render: (schedule) => (
        <span style={styles.enabledCell}>
          <EnabledDot enabled={schedule.enabled} />
          {schedule.enabled ? 'on' : 'off'}
        </span>
      ),
    },
    {
      key: 'name', header: 'Name',
      render: (schedule) => <span style={R.titleCellStyle()} title={schedule.name}>{schedule.name}</span>,
    },
    {
      key: 'target', header: target === 'workflow' ? 'Workflow' : 'Coder·model', width: '10rem',
      render: (schedule) => (
        <span style={styles.detailCell}>
          <TargetDetailCell
            schedule={schedule}
            target={target}
            workflowName={workflowNames[schedule.workflow_id ?? ''] ?? null}
          />
        </span>
      ),
    },
    {
      key: 'cron', header: 'Cron', width: '8rem',
      render: (schedule) => (
        <span style={R.merge(R.monoStyle(), styles.cell)} title={`${schedule.cron} (${schedule.timezone})`}>
          {schedule.cron}
        </span>
      ),
    },
    {
      key: 'next', header: 'Next run', width: '9rem',
      render: (schedule) => (
        <span style={styles.cell}>
          {schedule.enabled && schedule.next_fire_at ? fmtTs(schedule.next_fire_at) : <span style={R.dimStyle()}>—</span>}
        </span>
      ),
    },
    {
      key: 'last', header: 'Last run', width: '6.5rem',
      render: (schedule) => <TriggerLastRunCell schedule={schedule} />,
    },
  ];
  if (target === 'workflow') {
    cols.push({
      key: 'overlap', header: 'Overlap', width: '4rem',
      render: (schedule) => <span style={styles.cell}>{schedule.overlap}</span>,
    });
  }
  cols.push({
    key: 'runs', header: 'Runs', width: '3rem',
    render: (schedule) => <span style={styles.runsCell}>{schedule.run_count}</span>,
  });
  return cols;
}

// Mobile card body for one trigger (DataList wraps it in the card shell).
export function TriggerCard({
  schedule, target, workflowName,
}: {
  schedule: Schedule; target: TriggerTarget; workflowName: string | null;
}) {
  return (
    <>
      <div style={R.cardHeadStyle()}>
        <EnabledDot enabled={schedule.enabled} />
        <span style={R.cardTitleStyle()} title={schedule.name}>{schedule.name}</span>
        <TriggerLastRunCell schedule={schedule} />
      </div>
      <div style={R.cardMetaStyle()}>
        <TargetDetailCell schedule={schedule} target={target} workflowName={workflowName} />
      </div>
      <div style={R.merge(R.monoStyle(), R.cardMetaTextStyle())} title={`${schedule.cron} (${schedule.timezone})`}>
        {schedule.cron}
      </div>
      <div style={R.cardMetaStyle()}>
        <span style={R.cardMetaTextStyle()}>
          Next: {schedule.enabled && schedule.next_fire_at ? fmtTs(schedule.next_fire_at) : '—'}
        </span>
        <span style={R.cardMetaTextStyle()}>{schedule.run_count} run{schedule.run_count === 1 ? '' : 's'}</span>
        {target === 'workflow' && <span style={R.cardMetaTextStyle()}>{schedule.overlap}</span>}
      </div>
    </>
  );
}

const styles = {
  dot: {
    display: 'inline-block', width: '0.5rem', height: '0.5rem',
    borderRadius: '50%', flexShrink: 0,
  } as React.CSSProperties,
  dotOn: { background: T.colors.success } as React.CSSProperties,
  dotOff: { background: T.colors.border } as React.CSSProperties,
  enabledCell: {
    display: 'inline-flex', alignItems: 'center', gap: '0.375rem',
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  detailCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  link: { color: T.colors.link, textDecoration: 'none' } as React.CSSProperties,
  runLink: { display: 'inline-flex', textDecoration: 'none' } as React.CSSProperties,
  cell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  runsCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary, textAlign: 'right' as const,
  } as React.CSSProperties,
};
