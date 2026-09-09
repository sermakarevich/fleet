/**
 * One workflow run as a read-only stage grid: header with status and
 * actions, one column per stage of step cards linking to their tasks,
 * plus a newest-first timeline. Called by App's /workflow-runs/:runId
 * route; data comes from useWorkflowRun (polls while running).
 */
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { useCancelWorkflowRun, useWorkflow, useWorkflowRun } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import { statusLabel } from '../../shared/status';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import type { WorkflowStepRun } from '../../shared/types';
import { StatusChip } from '../../shared/ui/StatusChip';
import { TriggerChip, RunStatusChip } from './RunRow';

// One read-only step card: name, task title, task chip, state, task link.
function StepCard({ step }: { step: WorkflowStepRun }) {
  const attention = step.state === 'attention';
  return (
    <div style={R.merge(styles.stepCard, attention && styles.attentionCard)}>
      <div style={styles.stepName} title={step.step_name}>{step.step_name}</div>
      <div style={styles.taskTitle} title={step.task_title ?? step.task_id}>
        {step.task_title ?? step.task_id}
      </div>
      <div style={styles.stepMeta}>
        <StatusChip status={step.task_status} />
        <span style={styles.stateLabel}>{statusLabel(step.state)}</span>
      </div>
      <Link to={`/tasks/${step.task_id}`} style={styles.taskLink}>
        Open task {step.task_id}
      </Link>
    </div>
  );
}

// One stage column: header plus its step cards in run order.
function StageColumnView({ title, steps }: { title: string; steps: WorkflowStepRun[] }) {
  return (
    <div style={styles.stageCol}>
      <div style={styles.stageHead}>{title}</div>
      {steps.map((step) => (
        <StepCard key={step.step_name} step={step} />
      ))}
    </div>
  );
}

// Plain newest-first list of step status changes.
function Timeline({ steps }: { steps: WorkflowStepRun[] }) {
  const ordered = [...steps].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  return (
    <div style={styles.timeline}>
      <h3 style={styles.timelineHead}>Timeline</h3>
      {ordered.map((step) => (
        <div key={step.step_name} style={styles.timelineRow}>
          <span style={styles.timelineName}>{step.step_name}</span>
          <Link to={`/tasks/${step.task_id}`} style={styles.taskLink}>{step.task_id}</Link>
          <span style={styles.timelineTs}>{fmtTs(step.updated_at)}</span>
        </div>
      ))}
    </div>
  );
}

// Run detail: header, cancel/open actions, stage grid, timeline.
export function WorkflowRunPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { data: run, isLoading, error } = useWorkflowRun(runId ?? null);
  const { data: workflow } = useWorkflow(run?.workflow_id ?? null);
  const cancelRun = useCancelWorkflowRun();
  const [confirming, setConfirming] = useState(false);

  if (isLoading) return <p style={R.msgStyle()}>Loading…</p>;
  if (error || !run) return <p style={R.errorMsgStyle()}>Run not found.</p>;

  const cancellable = run.status === 'running' || run.status === 'attention';
  const runIdValue = run.id;
  const stageTitles = (workflow?.stages ?? []).map((s) => s.name);
  const stageIndexes = [...new Set(run.steps.map((s) => s.stage_index))].sort((a, b) => a - b);

  function onCancel() {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    cancelRun.mutate(runIdValue, { onSuccess: () => setConfirming(false) });
  }

  return (
    <div style={R.pageStyle(isMobile)}>
      <div style={R.topBarStyle()}>
        <h2 style={R.headingStyle()}>
          <Link to={`/workflows/${run.workflow_id}`}>{run.workflow_name}</Link>
          <span style={styles.runN}> #{run.n}</span>
        </h2>
        <TriggerChip trigger={run.trigger} />
        <RunStatusChip status={run.status} />
        <span style={styles.topActions}>
          {cancellable && (
            <button
              style={confirming ? T.btnDanger : T.btnGhost}
              disabled={cancelRun.isPending}
              title={confirming ? 'Click again to confirm' : 'Cancel this run'}
              onClick={onCancel}
            >
              {cancelRun.isPending ? 'Cancelling…' : confirming ? 'Confirm cancel' : 'Cancel run'}
            </button>
          )}
          <button style={T.btnGhost} onClick={() => navigate(`/workflows/${run.workflow_id}`)}>
            Open workflow
          </button>
        </span>
      </div>
      <p style={styles.metaLine}>
        Started {fmtTs(run.started_at)} · Finished {run.finished_at ? fmtTs(run.finished_at) : '—'}
      </p>
      {run.reason && <p style={styles.reasonLine}>{run.reason}</p>}
      <div style={styles.board}>
        {stageIndexes.map((index) => (
          <StageColumnView
            key={index}
            title={stageTitles[index] ?? `Stage ${index + 1}`}
            steps={run.steps.filter((s) => s.stage_index === index)}
          />
        ))}
      </div>
      <Timeline steps={run.steps} />
    </div>
  );
}

const styles = {
  runN: { color: '#d4d4d8' } as React.CSSProperties,
  topActions: {
    marginLeft: 'auto', display: 'inline-flex', gap: '0.5rem', alignItems: 'center',
  } as React.CSSProperties,
  metaLine: {
    fontSize: '0.8125rem', color: T.colors.textSecondary, margin: '0 0 0.25rem',
  } as React.CSSProperties,
  reasonLine: {
    fontSize: '0.875rem', color: T.colors.warningFg, background: T.colors.warningBg,
    borderRadius: 6, padding: '0.5rem 1rem', margin: '0 0 0.875rem',
  } as React.CSSProperties,
  board: {
    display: 'flex', gap: '0.75rem', overflowX: 'auto' as const,
    paddingBottom: '0.5rem', marginBottom: '1rem',
  } as React.CSSProperties,
  stageCol: {
    minWidth: '17rem', maxWidth: '17rem', flexShrink: 0,
    background: T.colors.bgDeep, border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: 6, padding: '0.625rem', display: 'flex',
    flexDirection: 'column' as const, gap: '0.5rem',
  } as React.CSSProperties,
  stageHead: { fontWeight: 600, fontSize: '0.875rem', color: T.colors.textPrimary } as React.CSSProperties,
  stepCard: {
    background: T.colors.bgElevated, border: `1px solid ${T.colors.border}`,
    borderRadius: 6, padding: '0.5rem', display: 'flex',
    flexDirection: 'column' as const, gap: '0.375rem',
  } as React.CSSProperties,
  attentionCard: { border: '1px solid #d97706' } as React.CSSProperties,
  stepName: {
    fontSize: '0.8125rem', fontWeight: 600, color: T.colors.textPrimary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  taskTitle: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  stepMeta: { display: 'flex', alignItems: 'center', gap: '0.5rem' } as React.CSSProperties,
  stateLabel: { fontSize: '0.75rem', color: T.colors.textSecondary } as React.CSSProperties,
  taskLink: { fontSize: '0.75rem', color: T.colors.accent } as React.CSSProperties,
  timeline: {
    background: T.colors.bgDeep, border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: 6, padding: '0.625rem 0.875rem',
  } as React.CSSProperties,
  timelineHead: {
    fontSize: '0.875rem', fontWeight: 600, color: T.colors.textPrimary, margin: '0 0 0.5rem',
  } as React.CSSProperties,
  timelineRow: {
    display: 'flex', alignItems: 'center', gap: '0.75rem',
    fontSize: '0.8125rem', padding: '0.25rem 0',
    borderTop: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  timelineName: {
    width: '10rem', flexShrink: 0, color: T.colors.textPrimary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  timelineTs: {
    marginLeft: 'auto', flexShrink: 0, fontSize: '0.75rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
};
