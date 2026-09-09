/**
 * One recurring workflow schedule as a table row (desktop) or a card
 * (mobile). Called by RecurringTable; selection is owned by RecurringPage.
 * The workflow name is resolved by the table from useWorkflows() and passed
 * in so rows stay pure and unit-testable without a query client.
 */
import { Link } from 'react-router-dom';
import type { Schedule } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { useClickableProps } from '../../shared/ui/Clickable';
import { RunStatusChip } from '../workflows/RunRow';

interface Props {
  schedule: Schedule;
  /** Display name of schedule.workflow_id, or null when unknown. */
  workflowName: string | null;
  selected: boolean;
  onSelect: (id: string) => void;
}

// Green when enabled, dim gray when disabled.
function EnabledDot({ enabled }: { enabled: boolean }) {
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
function WorkflowCell({ schedule, workflowName }: { schedule: Schedule; workflowName: string | null }) {
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

// Desktop table row for one recurring schedule.
export function RecurringRow({ schedule, workflowName, selected, onSelect }: Props) {
  const rowClick = useClickableProps(() => onSelect(schedule.id));
  return (
    <div style={R.rowStyle(selected)} className="row-interactive" {...rowClick}>
      <span style={styles.enabledCell}>
        <EnabledDot enabled={schedule.enabled} />
        {schedule.enabled ? 'on' : 'off'}
      </span>
      <span style={R.titleCellStyle()} title={schedule.name}>
        {schedule.name}
      </span>
      <span style={styles.workflowCell}>
        <WorkflowCell schedule={schedule} workflowName={workflowName} />
      </span>
      <span
        style={R.merge(R.monoStyle(), styles.cronCell)}
        title={`${schedule.cron} (${schedule.timezone})`}
      >
        {schedule.cron}
      </span>
      <span style={styles.nextCell}>
        {schedule.enabled && schedule.next_fire_at ? (
          fmtTs(schedule.next_fire_at)
        ) : (
          <span style={R.dimStyle()}>—</span>
        )}
      </span>
      <span style={styles.lastCell}>
        <RecurringLastRunCell schedule={schedule} />
      </span>
      <span style={styles.overlapCell}>{schedule.overlap}</span>
      <span style={styles.runsCell}>{schedule.run_count}</span>
    </div>
  );
}

// Mobile card for one recurring schedule.
export function RecurringCard({ schedule, workflowName, selected, onSelect }: Props) {
  const cardClick = useClickableProps(() => onSelect(schedule.id));
  return (
    <div
      style={R.merge(styles.card, R.when(selected, styles.cardSelected))}
      className="row-interactive"
      {...cardClick}
    >
      <div style={styles.cardHead}>
        <EnabledDot enabled={schedule.enabled} />
        <span style={styles.cardName} title={schedule.name}>
          {schedule.name}
        </span>
        <RecurringLastRunCell schedule={schedule} />
      </div>
      <div style={styles.cardMeta}>
        <WorkflowCell schedule={schedule} workflowName={workflowName} />
      </div>
      <div
        style={R.merge(R.monoStyle(), styles.cardCron)}
        title={`${schedule.cron} (${schedule.timezone})`}
      >
        {schedule.cron}
      </div>
      <div style={styles.cardMeta}>
        <span style={styles.cardMetaText}>
          Next: {schedule.enabled && schedule.next_fire_at ? fmtTs(schedule.next_fire_at) : '—'}
        </span>
        <span style={styles.cardMetaText}>
          {schedule.run_count} run{schedule.run_count === 1 ? '' : 's'}
        </span>
        <span style={styles.cardMetaText}>{schedule.overlap}</span>
      </div>
    </div>
  );
}

const styles = {
  dot: {
    display: 'inline-block',
    width: '0.5rem',
    height: '0.5rem',
    borderRadius: '9999px',
    flexShrink: 0,
  } as React.CSSProperties,
  dotOn: { background: T.colors.success } as React.CSSProperties,
  dotOff: { background: T.colors.border } as React.CSSProperties,
  enabledCell: {
    width: '4rem',
    flexShrink: 0,
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.375rem',
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  workflowCell: {
    width: '10rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  workflowLink: {
    color: '#60a5fa',
    textDecoration: 'none',
  } as React.CSSProperties,
  runLink: {
    display: 'inline-flex',
    textDecoration: 'none',
  } as React.CSSProperties,
  cronCell: {
    width: '8rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  nextCell: {
    width: '9rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  lastCell: {
    width: '6.5rem',
    flexShrink: 0,
  } as React.CSSProperties,
  overlapCell: {
    width: '4rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  runsCell: {
    width: '3rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
    textAlign: 'right' as const,
  } as React.CSSProperties,
  card: {
    padding: '0.625rem 0.875rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.3rem',
    fontSize: '0.875rem',
    color: '#d4d4d8',
  } as React.CSSProperties,
  cardSelected: {
    background: T.colors.borderSubtle,
  } as React.CSSProperties,
  cardHead: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  } as React.CSSProperties,
  cardName: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardCron: {
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  cardMeta: {
    display: 'flex',
    gap: '0.625rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  cardMetaText: {
    fontSize: '0.75rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
};
