// Per-schedule cell renderers for the shared DataList: desktop
// column definitions plus the mobile card body. Workflow names resolve
// in the page (via useWorkflows) and pass in as a plain lookup so the
// cells stay pure. Rendered by RecurringPage via DataList.
import { Link } from 'react-router-dom';
import type { Schedule } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { RunStatusChip } from '../workflows/runColumns';
import type { DataColumn } from '../../shared/ui/DataList';

// Green when enabled, dim gray when disabled.
export function EnabledDot({ enabled }: { enabled: boolean }) {
  return (
    <span
      title={enabled ? 'enabled' : 'disabled'}
      style={R.merge(styles.dot, enabled ? styles.dotOn : styles.dotOff)}
    />
  );
}

// Last-run cell: run status chip linking to the workflow run, "skipped",
// or "never". The inner link must not select the row.
export function RecurringLastRunCell({ schedule }: { schedule: Schedule }) {
  const last = schedule.last_run;
  if (!last) return <span style={R.dimStyle()}>never</span>;
  if (last.skipped || !last.workflow_run_id) return <span style={R.dimStyle()}>skipped</span>;
  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <Link
      to={`/workflow-runs/${last.workflow_run_id}`}
      onClick={stop}
      style={styles.runLink}
    >
      <RunStatusChip status={last.workflow_run_status ?? 'unknown'} />
    </Link>
  );
}

// Workflow cell: link to the definition, falling back to the raw id.
export function WorkflowCell({
  schedule,
  workflowName,
}: {
  schedule: Schedule;
  workflowName: string | null;
}) {
  if (!schedule.workflow_id) return <span style={R.dimStyle()}>—</span>;
  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <Link
      to={`/workflows/${schedule.workflow_id}`}
      onClick={stop}
      style={styles.workflowLink}
      title={schedule.workflow_id}
    >
      {workflowName ?? schedule.workflow_id}
    </Link>
  );
}

// Desktop columns for the recurring DataList.
export function recurringColumns(
  workflowNames: Record<string, string>,
): Array<DataColumn<Schedule>> {
  return [
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
      key: 'workflow', header: 'Workflow', width: '10rem',
      render: (schedule) => (
        <span style={styles.workflowCell}>
          <WorkflowCell schedule={schedule} workflowName={workflowNames[schedule.workflow_id ?? ''] ?? null} />
        </span>
      ),
    },
    {
      key: 'cron', header: 'Cron', width: '8rem',
      render: (schedule) => (
        <span style={R.merge(R.monoStyle(), styles.cronCell)} title={`${schedule.cron} (${schedule.timezone})`}>
          {schedule.cron}
        </span>
      ),
    },
    {
      key: 'next', header: 'Next run', width: '9rem',
      render: (schedule) => (
        <span style={styles.nextCell}>
          {schedule.enabled && schedule.next_fire_at ? fmtTs(schedule.next_fire_at) : <span style={R.dimStyle()}>—</span>}
        </span>
      ),
    },
    {
      key: 'last', header: 'Last run', width: '6.5rem',
      render: (schedule) => <RecurringLastRunCell schedule={schedule} />,
    },
    {
      key: 'overlap', header: 'Overlap', width: '4rem',
      render: (schedule) => <span style={styles.overlapCell}>{schedule.overlap}</span>,
    },
    {
      key: 'runs', header: 'Runs', width: '3rem',
      render: (schedule) => <span style={styles.runsCell}>{schedule.run_count}</span>,
    },
  ];
}

// Mobile card body for one recurring schedule.
export function RecurringCard({
  schedule,
  workflowName,
}: {
  schedule: Schedule;
  workflowName: string | null;
}) {
  return (
    <>
      <div style={R.cardHeadStyle()}>
        <EnabledDot enabled={schedule.enabled} />
        <span style={R.cardTitleStyle()} title={schedule.name}>{schedule.name}</span>
        <RecurringLastRunCell schedule={schedule} />
      </div>
      <div style={R.cardMetaStyle()}>
        <WorkflowCell schedule={schedule} workflowName={workflowName} />
      </div>
      <div style={R.merge(R.monoStyle(), R.cardMetaTextStyle())} title={`${schedule.cron} (${schedule.timezone})`}>
        {schedule.cron}
      </div>
      <div style={R.cardMetaStyle()}>
        <span style={R.cardMetaTextStyle()}>
          Next: {schedule.enabled && schedule.next_fire_at ? fmtTs(schedule.next_fire_at) : '—'}
        </span>
        <span style={R.cardMetaTextStyle()}>
          {schedule.run_count} run{schedule.run_count === 1 ? '' : 's'}
        </span>
        <span style={R.cardMetaTextStyle()}>{schedule.overlap}</span>
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
  workflowCell: {
    fontSize: '0.8125rem', overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  workflowLink: {
    color: T.colors.link, textDecoration: 'none',
  } as React.CSSProperties,
  runLink: {
    display: 'inline-flex', textDecoration: 'none',
  } as React.CSSProperties,
  cronCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  nextCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  overlapCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  runsCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary, textAlign: 'right' as const,
  } as React.CSSProperties,
};
