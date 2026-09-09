/**
 * Paged list of workflow runs with column headers and an empty state.
 * Called by WorkflowsPage (the Runs view) and the per-workflow runs route;
 * rows render via RunRow/RunCard.
 */
import type { WorkflowRun } from '../../shared/types';
import * as R from '../../shared/styles/recipes';
import { RunCard, RunRow } from './RunRow';

interface Props {
  runs: WorkflowRun[];
  onOpen: (runId: string) => void;
  isMobile: boolean;
}

// Table of runs with headers and an empty state.
export function RunsTable({ runs, onOpen, isMobile }: Props) {
  return (
    <div style={R.panelStyle()}>
      {!isMobile && (
        <div style={R.colHeaderStyle()}>
          <span style={R.titleCellStyle()}>Workflow</span>
          <span style={styles.cN}>#</span>
          <span style={styles.cTrigger}>Trigger</span>
          <span style={styles.cTs}>Started</span>
          <span style={styles.cTs}>Finished</span>
          <span style={styles.cStatus}>Status</span>
          <span style={styles.cProgress}>Progress</span>
        </div>
      )}
      {runs.length === 0 ? (
        <p style={R.emptyStyle()}>
          No runs yet. Start a run from a workflow with the Run button.
        </p>
      ) : (
        runs.map((run) =>
          isMobile ? (
            <RunCard key={run.id} run={run} onOpen={onOpen} />
          ) : (
            <RunRow key={run.id} run={run} onOpen={onOpen} />
          ),
        )
      )}
    </div>
  );
}

const styles = {
  cN:       { width: '3rem', flexShrink: 0 } as React.CSSProperties,
  cTrigger: { width: '5rem', flexShrink: 0 } as React.CSSProperties,
  cTs:      { width: '8rem', flexShrink: 0 } as React.CSSProperties,
  cStatus:  { width: '6.5rem', flexShrink: 0 } as React.CSSProperties,
  cProgress:{ flex: 1, minWidth: '8rem' } as React.CSSProperties,
};
