// Per-schedule cell renderers for the shared DataList: desktop
// column definitions plus the mobile card body. The enabled dot and
// last-run cell stay unit-testable pure renderers. Rendered by
// SchedulesPage via DataList.
import type { Schedule } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { StatusChip } from '../../shared/ui/StatusChip';
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

// Last-run cell: task status chip, "skipped", or "never".
export function LastRunCell({ schedule }: { schedule: Schedule }) {
  const last = schedule.last_run;
  if (!last) return <span style={R.dimStyle()}>never</span>;
  if (last.skipped) return <span style={R.dimStyle()}>skipped</span>;
  return <StatusChip status={last.task_status ?? 'unknown'} width="6rem" />;
}

// Desktop columns for the schedules DataList.
export function scheduleColumns(): Array<DataColumn<Schedule>> {
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
      render: (schedule) => <LastRunCell schedule={schedule} />,
    },
    {
      key: 'coder', header: 'Coder', width: '7rem',
      render: (schedule) => (
        <span style={styles.coderCell} title={`${schedule.coder ?? '—'} / ${schedule.model ?? '—'}`}>
          {schedule.coder ?? <span style={R.dimStyle()}>—</span>}
        </span>
      ),
    },
    {
      key: 'runs', header: 'Runs', width: '3rem',
      render: (schedule) => <span style={styles.runsCell}>{schedule.run_count}</span>,
    },
  ];
}

// Mobile card body for one schedule (DataList wraps it in the card shell).
export function ScheduleCard({ schedule }: { schedule: Schedule }) {
  return (
    <>
      <div style={R.cardHeadStyle()}>
        <EnabledDot enabled={schedule.enabled} />
        <span style={R.cardTitleStyle()} title={schedule.name}>{schedule.name}</span>
        <LastRunCell schedule={schedule} />
      </div>
      <div style={R.merge(R.monoStyle(), R.cardMetaTextStyle())} title={`${schedule.cron} (${schedule.timezone})`}>
        {schedule.cron}
      </div>
      <div style={R.cardMetaStyle()}>
        <span style={R.cardMetaTextStyle()}>
          Next: {schedule.enabled && schedule.next_fire_at ? fmtTs(schedule.next_fire_at) : '—'}
        </span>
        <span style={R.cardMetaTextStyle()}>{schedule.run_count} run{schedule.run_count === 1 ? '' : 's'}</span>
        {schedule.coder && <span style={R.cardMetaTextStyle()}>{schedule.coder}</span>}
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
    width: '4rem', flexShrink: 0, display: 'inline-flex',
    alignItems: 'center', gap: '0.375rem', fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  cronCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  nextCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  coderCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  runsCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary, textAlign: 'right' as const,
  } as React.CSSProperties,
};
