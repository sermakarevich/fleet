/**
 * Schedule list with column headers and row selection.
 * Called by SchedulesPage; rows render via ScheduleRow/ScheduleCard.
 */
import type { Schedule } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { ScheduleCard, ScheduleRow } from './ScheduleRow';

interface Props {
  items: Schedule[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  isMobile: boolean;
}

// Table of schedules with headers and an empty state.
export function SchedulesTable({ items, selectedId, onSelect, isMobile }: Props) {
  return (
    <div style={R.panelStyle()}>
      {!isMobile && (
        <div style={R.colHeaderStyle()}>
          <span style={styles.cEnabled}>Enabled</span>
          <span style={styles.cName}>Name</span>
          <span style={styles.cCron}>Cron</span>
          <span style={styles.cNext}>Next run</span>
          <span style={styles.cLast}>Last run</span>
          <span style={styles.cCoder}>Coder</span>
          <span style={styles.cRuns}>Runs</span>
        </div>
      )}
      {items.length === 0 ? (
        <p style={R.emptyStyle()}>No schedules yet. Create one to run a worker on a cron.</p>
      ) : (
        items.map((schedule) =>
          isMobile ? (
            <ScheduleCard key={schedule.id} schedule={schedule} selected={selectedId === schedule.id} onSelect={onSelect} />
          ) : (
            <ScheduleRow key={schedule.id} schedule={schedule} selected={selectedId === schedule.id} onSelect={onSelect} />
          ),
        )
      )}
    </div>
  );
}

const styles = {
  cEnabled: { width: '4rem', flexShrink: 0 } as React.CSSProperties,
  cName:    { flex: 1, minWidth: 0 } as React.CSSProperties,
  cCron:    { width: '8rem', flexShrink: 0 } as React.CSSProperties,
  cNext:    { width: '9rem', flexShrink: 0 } as React.CSSProperties,
  cLast:    { width: '6.5rem', flexShrink: 0 } as React.CSSProperties,
  cCoder:   { width: '7rem', flexShrink: 0 } as React.CSSProperties,
  cRuns:    { width: '3rem', flexShrink: 0, textAlign: 'right' as const } as React.CSSProperties,
};
