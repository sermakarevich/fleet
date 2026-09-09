/**
 * One workflow as a table row (desktop) or a card (mobile), with Run,
 * Edit, Export and two-step Delete actions.
 * Called by WorkflowsTable; navigation and mutations live in WorkflowsPage.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Workflow } from '../../shared/types';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { runStatusColor, statusLabel } from '../../shared/status';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { useClickableProps } from '../../shared/ui/Clickable';

interface Props {
  workflow: Workflow;
  onEdit: (id: string) => void;
  onRun: (id: string) => void;
  onDelete: (id: string) => void;
  running: boolean;
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
export function LastRunCell({ workflow }: { workflow: Workflow }) {
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
// two-step Delete.
function RowActions({ workflow, onRun, onEdit, onDelete, running }: Props) {
  const [confirming, setConfirming] = useState(false);
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
        onClick={(e) => { stop(e); onRun(workflow.id); }}
      >
        {running ? 'Starting…' : 'Run'}
      </button>
      <button
        style={T.btnGhost}
        title="Edit stages and steps"
        onClick={(e) => { stop(e); onEdit(workflow.id); }}
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
        <button
          style={R.merge(T.btnDanger, styles.deleteBtn)}
          title="Click again to confirm"
          onClick={(e) => { stop(e); onDelete(workflow.id); }}
        >
          Confirm delete
        </button>
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

// Desktop table row for one workflow.
export function WorkflowRow(props: Props) {
  const { workflow, onEdit } = props;
  const rowClick = useClickableProps(() => onEdit(workflow.id));
  return (
    <div style={R.rowStyle(false)} className="row-interactive" {...rowClick}>
      <span style={R.titleCellStyle()} title={workflow.name}>{workflow.name}</span>
      <span style={styles.shapeCol}>
        <ShapeCell workflow={workflow} />
      </span>
      <span style={styles.lastCol}>
        <LastRunCell workflow={workflow} />
      </span>
      <span style={styles.runsCol}>{workflow.run_count}</span>
      <span style={styles.updatedCol}>{fmtTs(workflow.updated_at)}</span>
      <RowActions {...props} />
    </div>
  );
}

// Mobile card for one workflow.
export function WorkflowCard(props: Props) {
  const { workflow, onEdit } = props;
  const cardClick = useClickableProps(() => onEdit(workflow.id));
  return (
    <div style={styles.card} className="row-interactive" {...cardClick}>
      <div style={styles.cardHead}>
        <span style={styles.cardName} title={workflow.name}>{workflow.name}</span>
        <LastRunCell workflow={workflow} />
      </div>
      <div style={styles.cardMeta}>
        <ShapeCell workflow={workflow} />
      </div>
      <div style={styles.cardMeta}>
        <span style={styles.cardMetaText}>
          {workflow.run_count} run{workflow.run_count === 1 ? '' : 's'} · updated {fmtTs(workflow.updated_at)}
        </span>
      </div>
      <RowActions {...props} />
    </div>
  );
}

const styles = {
  shapeCell: {
    display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  strip: {
    display: 'inline-flex', alignItems: 'center', gap: '2px',
  } as React.CSSProperties,
  stripBox: {
    display: 'inline-block', height: '0.625rem',
    background: T.colors.accent, borderRadius: 2, flexShrink: 0,
  } as React.CSSProperties,
  shapeCol: { width: '12rem', flexShrink: 0 } as React.CSSProperties,
  lastCol: { width: '6.5rem', flexShrink: 0 } as React.CSSProperties,
  runsCol: {
    width: '3rem', flexShrink: 0, fontSize: '0.8125rem',
    color: T.colors.textSecondary, textAlign: 'right' as const,
  } as React.CSSProperties,
  updatedCol: {
    width: '8rem', flexShrink: 0, fontSize: '0.8125rem', color: T.colors.textSecondary,
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
  deleteBtn: { padding: '0.2rem 0.625rem', fontSize: '0.8125rem' } as React.CSSProperties,
  card: {
    padding: '0.625rem 0.875rem', borderBottom: `1px solid ${T.colors.borderSubtle}`,
    cursor: 'pointer', display: 'flex', flexDirection: 'column' as const,
    gap: '0.3rem', fontSize: '0.875rem', color: T.colors.textBody,
  } as React.CSSProperties,
  cardHead: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
  } as React.CSSProperties,
  cardName: {
    flex: 1, minWidth: 0, overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardMeta: {
    display: 'flex', gap: '0.625rem', flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  cardMetaText: {
    fontSize: '0.75rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
};
