/**
 * One schedule as a table row (desktop) or a card (mobile).
 * Called by SchedulesTable; selection is owned by SchedulesPage.
 */
import type { Schedule } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { useClickableProps } from '../../shared/ui/Clickable';
import { StatusChip } from '../../shared/ui/StatusChip';

interface Props {
  schedule: Schedule;
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

// Last-run cell: task status chip, "skipped", or "never".
export function LastRunCell({ schedule }: { schedule: Schedule }) {
  const last = schedule.last_run;
  if (!last) return <span style={R.dimStyle()}>never</span>;
  if (last.skipped) return <span style={R.dimStyle()}>skipped</span>;
  return <StatusChip status={last.task_status ?? 'unknown'} width="6rem" />;
}

// Desktop table row for one schedule.
export function ScheduleRow({ schedule, selected, onSelect }: Props) {
  const rowClick = useClickableProps(() => onSelect(schedule.id));
  return (
    <div style={R.rowStyle(selected)} className="row-interactive" {...rowClick}>
      <span style={styles.enabledCell}>
        <EnabledDot enabled={schedule.enabled} />
        {schedule.enabled ? 'on' : 'off'}
      </span>
      <span style={R.titleCellStyle()} title={schedule.name}>{schedule.name}</span>
      <span style={R.merge(R.monoStyle(), styles.cronCell)} title={`${schedule.cron} (${schedule.timezone})`}>
        {schedule.cron}
      </span>
      <span style={styles.nextCell}>
        {schedule.enabled && schedule.next_fire_at ? fmtTs(schedule.next_fire_at) : <span style={R.dimStyle()}>—</span>}
      </span>
      <span style={styles.lastCell}>
        <LastRunCell schedule={schedule} />
      </span>
      <span style={styles.coderCell} title={`${schedule.coder ?? '—'} / ${schedule.model ?? '—'}`}>
        {schedule.coder ?? <span style={R.dimStyle()}>—</span>}
      </span>
      <span style={styles.runsCell}>{schedule.run_count}</span>
    </div>
  );
}

// Mobile card for one schedule.
export function ScheduleCard({ schedule, selected, onSelect }: Props) {
  const cardClick = useClickableProps(() => onSelect(schedule.id));
  return (
    <div
      style={R.merge(styles.card, R.when(selected, styles.cardSelected))}
      className="row-interactive"
      {...cardClick}
    >
      <div style={styles.cardHead}>
        <EnabledDot enabled={schedule.enabled} />
        <span style={styles.cardName} title={schedule.name}>{schedule.name}</span>
        <LastRunCell schedule={schedule} />
      </div>
      <div style={R.merge(R.monoStyle(), styles.cardCron)} title={`${schedule.cron} (${schedule.timezone})`}>
        {schedule.cron}
      </div>
      <div style={styles.cardMeta}>
        <span style={styles.cardMetaText}>
          Next: {schedule.enabled && schedule.next_fire_at ? fmtTs(schedule.next_fire_at) : '—'}
        </span>
        <span style={styles.cardMetaText}>{schedule.run_count} run{schedule.run_count === 1 ? '' : 's'}</span>
        {schedule.coder && <span style={styles.cardMetaText}>{schedule.coder}</span>}
      </div>
    </div>
  );
}

const styles = {
  dot: {
    display: 'inline-block', width: '0.5rem', height: '0.5rem',
    borderRadius: '9999px', flexShrink: 0,
  } as React.CSSProperties,
  dotOn: { background: T.colors.success } as React.CSSProperties,
  dotOff: { background: T.colors.border } as React.CSSProperties,
  enabledCell: {
    width: '4rem', flexShrink: 0, display: 'inline-flex',
    alignItems: 'center', gap: '0.375rem', fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  cronCell: {
    width: '8rem', flexShrink: 0, fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  nextCell: {
    width: '9rem', flexShrink: 0, fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  lastCell: {
    width: '6.5rem', flexShrink: 0,
  } as React.CSSProperties,
  coderCell: {
    width: '7rem', flexShrink: 0, fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  runsCell: {
    width: '3rem', flexShrink: 0, fontSize: '0.8125rem',
    color: T.colors.textSecondary, textAlign: 'right' as const,
  } as React.CSSProperties,
  card: {
    padding: '0.625rem 0.875rem', borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer', display: 'flex', flexDirection: 'column' as const,
    gap: '0.3rem', fontSize: '0.875rem', color: '#d4d4d8',
  } as React.CSSProperties,
  cardSelected: {
    background: T.colors.borderSubtle,
  } as React.CSSProperties,
  cardHead: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
  } as React.CSSProperties,
  cardName: {
    flex: 1, minWidth: 0, overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardCron: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  cardMeta: {
    display: 'flex', gap: '0.625rem', flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  cardMetaText: {
    fontSize: '0.75rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
};
