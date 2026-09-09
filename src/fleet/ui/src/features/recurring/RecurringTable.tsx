/**
 * Recurring-workflow schedule list with column headers and row selection.
 * Called by RecurringPage; rows render via RecurringRow/RecurringCard with
 * workflow names resolved from useWorkflows() into a plain lookup.
 */
import type { Schedule } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { RecurringCard, RecurringRow } from './RecurringRow';

interface Props {
  items: Schedule[];
  /** Workflow id to display name, built by the page from useWorkflows(). */
  workflowNames: Record<string, string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  isMobile: boolean;
}

// Table of recurring schedules with headers and an empty state.
export function RecurringTable({ items, workflowNames, selectedId, onSelect, isMobile }: Props) {
  return (
    <div style={R.panelStyle()}>
      {!isMobile && (
        <div style={R.colHeaderStyle()}>
          <span style={styles.cEnabled}>Enabled</span>
          <span style={styles.cName}>Name</span>
          <span style={styles.cWorkflow}>Workflow</span>
          <span style={styles.cCron}>Cron</span>
          <span style={styles.cNext}>Next run</span>
          <span style={styles.cLast}>Last run</span>
          <span style={styles.cOverlap}>Overlap</span>
          <span style={styles.cRuns}>Runs</span>
        </div>
      )}
      {items.length === 0 ? (
        <p style={R.emptyStyle()}>
          No recurring workflows. Pick a workflow and a cron to run it on a timer.
        </p>
      ) : (
        items.map((schedule) =>
          isMobile ? (
            <RecurringCard
              key={schedule.id}
              schedule={schedule}
              workflowName={workflowNames[schedule.workflow_id ?? ''] ?? null}
              selected={selectedId === schedule.id}
              onSelect={onSelect}
            />
          ) : (
            <RecurringRow
              key={schedule.id}
              schedule={schedule}
              workflowName={workflowNames[schedule.workflow_id ?? ''] ?? null}
              selected={selectedId === schedule.id}
              onSelect={onSelect}
            />
          ),
        )
      )}
    </div>
  );
}

const styles = {
  cEnabled: { width: '4rem', flexShrink: 0 } as React.CSSProperties,
  cName: { flex: 1, minWidth: 0 } as React.CSSProperties,
  cWorkflow: { width: '10rem', flexShrink: 0 } as React.CSSProperties,
  cCron: { width: '8rem', flexShrink: 0 } as React.CSSProperties,
  cNext: { width: '9rem', flexShrink: 0 } as React.CSSProperties,
  cLast: { width: '6.5rem', flexShrink: 0 } as React.CSSProperties,
  cOverlap: { width: '4rem', flexShrink: 0 } as React.CSSProperties,
  cRuns: { width: '3rem', flexShrink: 0, textAlign: 'right' as const } as React.CSSProperties,
};
