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
import { Confirm } from '../../shared/ui/Confirm';
import { LoadingState } from '../../shared/ui/LoadingState';
import { TriggerChip, RunStatusChip } from './runColumns';

// One read-only step card: name, task title, task chip, state, task link,
// plus the step's outputs and warning (ADR 0010). A step whose bead is
// still deferred reads "waiting (deferred)".
function StepCard({ step }: { step: WorkflowStepRun }) {
  const attention = step.state === 'attention';
  const deferred = step.state === 'waiting' && step.task_status === 'deferred';
  const outputs = Object.entries(step.outputs ?? {});
  const stateText = deferred ? `${statusLabel(step.state)} (deferred)` : statusLabel(step.state);
  return (
    <div style={R.merge(styles.stepCard, attention && styles.attentionCard)}>
      <div style={styles.stepName} title={step.step_name}>{step.step_name}</div>
      <div style={styles.taskTitle} title={step.task_title ?? step.task_id}>
        {step.task_title ?? step.task_id}
      </div>
      <div style={styles.stepMeta}>
        <StatusChip status={step.task_status} />
        <span style={styles.stateLabel}>{stateText}</span>
      </div>
      {outputs.length > 0 && (
        <div style={styles.outputsBox}>
          {outputs.map(([key, value]) => (
            <div key={key} style={styles.outputRow}>
              <span style={styles.outputKey} title={key}>{key}:</span>
              <span style={styles.outputValue} title={value}>{value}</span>
            </div>
          ))}
        </div>
      )}
      {step.warning && (
        <div style={styles.warningBox} title={step.warning}>
          ⚠ {step.warning}
        </div>
      )}
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

  if (isLoading) return <LoadingState />;
  if (error || !run) return <p style={R.errorMsgStyle()}>Run not found.</p>;

  const cancellable = run.status === 'running' || run.status === 'attention';
  const runIdValue = run.id;
  const stageTitles = (workflow?.stages ?? []).map((s) => s.name);
  const stageIndexes = [...new Set(run.steps.map((s) => s.stage_index))].sort((a, b) => a - b);

  function onCancel() {
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
          {cancellable && !confirming && (
            <button
              style={T.btnGhost}
              disabled={cancelRun.isPending}
              title="Cancel this run"
              onClick={() => setConfirming(true)}
            >
              {cancelRun.isPending ? 'Cancelling…' : 'Cancel run'}
            </button>
          )}
          {cancellable && confirming && (
            <Confirm
              verb="Cancel run"
              onConfirm={onCancel}
              onCancel={() => setConfirming(false)}
            />
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
      {Object.keys(run.inputs ?? {}).length > 0 && (
        <div style={styles.inputsBox}>
          <h3 style={styles.inputsHead}>Inputs</h3>
          {Object.entries(run.inputs ?? {}).map(([name, value]) => (
            <div key={name} style={styles.inputRow}>
              <span style={styles.inputName} title={name}>{name}:</span>
              <span style={styles.inputValue} title={value}>{value}</span>
            </div>
          ))}
        </div>
      )}
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
  runN: { color: T.colors.textBody } as React.CSSProperties,
  topActions: {
    marginLeft: 'auto', display: 'inline-flex', gap: '0.5rem', alignItems: 'center',
  } as React.CSSProperties,
  metaLine: {
    fontSize: '0.8125rem', color: T.colors.textSecondary, margin: '0 0 0.25rem',
  } as React.CSSProperties,
  reasonLine: {
    fontSize: '0.875rem', color: T.colors.warningFg, background: T.colors.warningBg,
    borderRadius: '0.375rem', padding: '0.5rem 1rem', margin: '0 0 0.875rem',
  } as React.CSSProperties,
  board: {
    display: 'flex', gap: '0.75rem', overflowX: 'auto' as const,
    paddingBottom: '0.5rem', marginBottom: '1rem',
  } as React.CSSProperties,
  stageCol: {
    minWidth: '17rem', maxWidth: '17rem', flexShrink: 0,
    background: T.colors.bgDeep, border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.375rem', padding: '0.625rem', display: 'flex',
    flexDirection: 'column' as const, gap: '0.5rem',
  } as React.CSSProperties,
  stageHead: { fontWeight: 600, fontSize: '0.875rem', color: T.colors.textPrimary } as React.CSSProperties,
  stepCard: {
    background: T.colors.bgElevated, border: `1px solid ${T.colors.border}`,
    borderRadius: '0.375rem', padding: '0.5rem', display: 'flex',
    flexDirection: 'column' as const, gap: '0.375rem',
  } as React.CSSProperties,
  attentionCard: { border: `1px solid ${T.colors.amberDark}` } as React.CSSProperties,
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
  outputsBox: {
    display: 'flex', flexDirection: 'column' as const, gap: '0.125rem',
    background: T.colors.bgDeep, border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.25rem', padding: '0.375rem 0.5rem',
  } as React.CSSProperties,
  outputRow: {
    display: 'flex', gap: '0.375rem', fontSize: '0.75rem',
    minWidth: 0, alignItems: 'baseline',
  } as React.CSSProperties,
  outputKey: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    color: T.colors.textPrimary, flexShrink: 0,
  } as React.CSSProperties,
  outputValue: {
    color: T.colors.textSecondary, overflow: 'hidden', textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const, minWidth: 0, flex: 1,
  } as React.CSSProperties,
  warningBox: {
    fontSize: '0.75rem', color: T.colors.warningFg, background: T.colors.warningBg,
    borderRadius: '0.25rem', padding: '0.25rem 0.5rem',
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  inputsBox: {
    background: T.colors.bgDeep, border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.375rem', padding: '0.625rem 0.875rem', margin: '0 0 0.875rem',
  } as React.CSSProperties,
  inputsHead: {
    fontSize: '0.875rem', fontWeight: 600, color: T.colors.textPrimary, margin: '0 0 0.375rem',
  } as React.CSSProperties,
  inputRow: {
    display: 'flex', gap: '0.5rem', fontSize: '0.8125rem', padding: '0.125rem 0',
  } as React.CSSProperties,
  inputName: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    color: T.colors.textPrimary, flexShrink: 0,
  } as React.CSSProperties,
  inputValue: {
    color: T.colors.textBody, overflow: 'hidden', textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  taskLink: { fontSize: '0.75rem', color: T.colors.accent } as React.CSSProperties,
  timeline: {
    background: T.colors.bgDeep, border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.375rem', padding: '0.625rem 0.875rem',
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
