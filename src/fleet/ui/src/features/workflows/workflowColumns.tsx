// Per-workflow cell renderers for the shared DataList: desktop
// column definitions plus the mobile card body. Shape and last-run
// cells stay pure renderers; row actions (Run/Edit/Runs/Export/Delete)
// confirm deletion inline via the shared Confirm. Rendered by
// WorkflowsPage via DataList.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Workflow } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { runStatusColor, statusLabel } from '../../shared/status';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { Confirm } from '../../shared/ui/Confirm';
import type { DataColumn } from '../../shared/ui/DataList';

export interface WorkflowListCallbacks {
  onEdit: (id: string) => void;
  onRun: (id: string) => void;
  onDelete: (id: string) => void;
  runningId: string | null;
}

// Shape summary plus a tiny stage strip (one box per stage, width grows
// with the step count, title lists the step names).
export function ShapeCell({ workflow }: { workflow: Workflow }) {
  const stages = workflow.stages ?? [];
  const maxSteps = Math.max(1, ...stages.map((s) => (s.steps ?? []).length));
  return (
    <span style={styles.shapeCell}>
      <span>
        {workflow.stage_count} stage{workflow.stage_count === 1 ? '' : 's'} · {workflow.step_count} step
        {workflow.step_count === 1 ? '' : 's'}
      </span>
      <span style={styles.strip} aria-hidden="true">
        {stages.map((stage, i) => (
          <span
            key={`${stage.name}-${i}`}
            title={`${stage.name}: ${(stage.steps ?? []).map((s) => s.name).join(', ') || 'no steps'}`}
            style={R.merge(styles.stripBox, {
              width: `${0.5 + ((stage.steps ?? []).length / maxSteps) * 1.25}rem`,
            })}
          />
        ))}
      </span>
    </span>
  );
}

// Last-run cell: colored run-status chip linking to the run, or "never".
export function WorkflowLastRunCell({ workflow }: { workflow: Workflow }) {
  const last = workflow.last_run;
  if (!last) return <span style={R.dimStyle()}>never</span>;
  const { bg, fg } = runStatusColor(last.status);
  return (
    <Link
      to={`/workflow-runs/${last.id}`}
      onClick={(e) => e.stopPropagation()}
      style={R.merge(T.badge, { width: '6rem', flexShrink: 0, background: bg, color: fg, textDecoration: 'none' })}
    >
      {statusLabel(last.status)}
    </Link>
  );
}

// Row actions: Run, Edit, Runs (history), Export (plain download link),
// Delete with an inline shared Confirm.
export function WorkflowActions({
  workflow,
  cb,
}: {
  workflow: Workflow;
  cb: WorkflowListCallbacks;
}) {
  const [confirming, setConfirming] = useState(false);
  const running = cb.runningId === workflow.id;
  // The row itself navigates to the editor; actions must not bubble up.
  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <span style={styles.actions}>
      <button
        style={T.btnGhost}
        title="Start a run of this workflow"
        disabled={running}
        onClick={(e) => { stop(e); cb.onRun(workflow.id); }}
      >
        {running ? 'Starting…' : 'Run'}
      </button>
      <button
        style={T.btnGhost}
        title="Edit stages and steps"
        onClick={(e) => { stop(e); cb.onEdit(workflow.id); }}
      >
        Edit
      </button>
      <Link
        style={R.merge(T.btnGhost, styles.exportLink)}
        title="Past runs of this workflow"
        to={`/workflows/${workflow.id}/runs`}
        onClick={stop}
      >
        Runs
      </Link>
      <a
        style={R.merge(T.btnGhost, styles.exportLink)}
        title="Download as YAML"
        href={`/api/workflows/${workflow.id}/export?format=text`}
        download
        onClick={stop}
      >
        Export
      </a>
      {confirming ? (
        <Confirm
          verb="Delete"
          onConfirm={() => cb.onDelete(workflow.id)}
          onCancel={() => setConfirming(false)}
        />
      ) : (
        <button
          style={T.btnGhost}
          title="Delete this workflow"
          onClick={(e) => { stop(e); setConfirming(true); }}
        >
          Delete
        </button>
      )}
    </span>
  );
}

// Desktop columns for the workflows DataList.
export function workflowColumns(cb: WorkflowListCallbacks): Array<DataColumn<Workflow>> {
  return [
    {
      key: 'name', header: 'Name',
      render: (workflow) => <span style={R.titleCellStyle()} title={workflow.name}>{workflow.name}</span>,
    },
    {
      key: 'shape', header: 'Shape', width: '12rem',
      render: (workflow) => <ShapeCell workflow={workflow} />,
    },
    {
      key: 'last', header: 'Last run', width: '6.5rem',
      render: (workflow) => <WorkflowLastRunCell workflow={workflow} />,
    },
    {
      key: 'runs', header: 'Runs', width: '3rem',
      render: (workflow) => <span style={styles.runsCol}>{workflow.run_count}</span>,
    },
    {
      key: 'updated', header: 'Updated', width: '8rem',
      render: (workflow) => <span style={styles.updatedCol}>{fmtTs(workflow.updated_at)}</span>,
    },
    {
      key: 'actions', header: '',
      render: (workflow) => <WorkflowActions workflow={workflow} cb={cb} />,
    },
  ];
}

// Mobile card body for one workflow.
export function WorkflowCard({
  workflow,
  cb,
}: {
  workflow: Workflow;
  cb: WorkflowListCallbacks;
}) {
  return (
    <>
      <div style={R.cardHeadStyle()}>
        <span style={R.cardTitleStyle()} title={workflow.name}>{workflow.name}</span>
        <WorkflowLastRunCell workflow={workflow} />
      </div>
      <div style={R.cardMetaStyle()}>
        <ShapeCell workflow={workflow} />
      </div>
      <div style={R.cardMetaStyle()}>
        <span style={R.cardMetaTextStyle()}>
          {workflow.run_count} run{workflow.run_count === 1 ? '' : 's'} · updated {fmtTs(workflow.updated_at)}
        </span>
      </div>
      <WorkflowActions workflow={workflow} cb={cb} />
    </>
  );
}

const styles = {
  shapeCell: {
    display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  strip: {
    display: 'inline-flex', alignItems: 'center', gap: '0.125rem',
  } as React.CSSProperties,
  stripBox: {
    display: 'inline-block', height: '0.625rem',
    background: T.colors.accent, borderRadius: '0.125rem', flexShrink: 0,
  } as React.CSSProperties,
  runsCol: {
    fontSize: '0.8125rem', color: T.colors.textSecondary, textAlign: 'right' as const,
  } as React.CSSProperties,
  updatedCol: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  actions: {
    display: 'inline-flex', gap: '0.375rem', marginLeft: 'auto', flexShrink: 0,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  exportLink: {
    textDecoration: 'none', padding: '0.2rem 0.625rem', fontSize: '0.8125rem',
    display: 'inline-flex', alignItems: 'center',
  } as React.CSSProperties,
};
