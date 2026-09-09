/**
 * Workflow list with column headers and row selection.
 * Called by WorkflowsPage; rows render via WorkflowRow/WorkflowCard.
 */
import type { Workflow } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { WorkflowCard, WorkflowRow } from './WorkflowRow';

interface Props {
  items: Workflow[];
  onEdit: (id: string) => void;
  onRun: (id: string) => void;
  onDelete: (id: string) => void;
  runningId: string | null;
  isMobile: boolean;
}

// Table of workflows with headers and an empty state.
export function WorkflowsTable({ items, onEdit, onRun, onDelete, runningId, isMobile }: Props) {
  return (
    <div style={R.panelStyle()}>
      {!isMobile && (
        <div style={R.colHeaderStyle()}>
          <span style={R.titleCellStyle()}>Name</span>
          <span style={styles.cShape}>Shape</span>
          <span style={styles.cLast}>Last run</span>
          <span style={styles.cRuns}>Runs</span>
          <span style={styles.cUpdated}>Updated</span>
          <span style={styles.cActions} />
        </div>
      )}
      {items.length === 0 ? (
        <p style={R.emptyStyle()}>
          No workflows yet. Arrange workers into stages and save them as a workflow, or import a YAML file.
        </p>
      ) : (
        items.map((workflow) =>
          isMobile ? (
            <WorkflowCard
              key={workflow.id}
              workflow={workflow}
              onEdit={onEdit}
              onRun={onRun}
              onDelete={onDelete}
              running={runningId === workflow.id}
            />
          ) : (
            <WorkflowRow
              key={workflow.id}
              workflow={workflow}
              onEdit={onEdit}
              onRun={onRun}
              onDelete={onDelete}
              running={runningId === workflow.id}
            />
          ),
        )
      )}
    </div>
  );
}

const styles = {
  cShape:   { width: '12rem', flexShrink: 0 } as React.CSSProperties,
  cLast:    { width: '6.5rem', flexShrink: 0 } as React.CSSProperties,
  cRuns:    { width: '3rem', flexShrink: 0, textAlign: 'right' as const } as React.CSSProperties,
  cUpdated: { width: '8rem', flexShrink: 0 } as React.CSSProperties,
  cActions: { marginLeft: 'auto', flexShrink: 0, minWidth: '1rem' } as React.CSSProperties,
};
