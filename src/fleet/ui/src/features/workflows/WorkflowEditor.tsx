/**
 * Stage-board editor for one workflow: header fields, defaults, stage
 * columns of step cards, live problems and a save/run/export footer.
 * Called by WorkflowsPage for /workflows/new and /workflows/:id; all
 * state lives in useWorkflowEditor.
 */
import { useState } from 'react';
import { api, errorMessage } from '../../shared/api';
import { useWorkflow } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import type { Workflow } from '../../shared/types';
import { RunWorkflowModal } from './RunWorkflowModal';
import { ISOLATION_OPTIONS, useWorkflowEditor, type StageDraft, type StepDraft, type WorkflowEditorState } from './useWorkflowEditor';

interface Props {
  workflowId: string | null;
  onClose: () => void;
  onSaved: (workflow: Workflow) => void;
}

// Load the saved workflow for edit mode, then hand to the form.
export function WorkflowEditor({ workflowId, onClose, onSaved }: Props) {
  const { data, isLoading, error } = useWorkflow(workflowId);
  if (workflowId && isLoading) return <p style={R.msgStyle()}>Loading…</p>;
  if (workflowId && error) return <p style={R.errorMsgStyle()}>Error: {errorMessage(error)}</p>;
  if (workflowId && !data) return <p style={R.errorMsgStyle()}>Workflow not found.</p>;
  return <WorkflowEditorForm key={workflowId ?? 'new'} initial={data ?? null} onClose={onClose} onSaved={onSaved} />;
}

interface FormProps {
  initial: Workflow | null;
  onClose: () => void;
  onSaved: (workflow: Workflow) => void;
}

// One step card: identity fields, collapsible overrides and needs.
function StepCard({
  ed, stageIndex, stepIndex, step,
}: {
  ed: WorkflowEditorState;
  stageIndex: number;
  stepIndex: number;
  step: StepDraft;
}) {
  const options = ed.needsOptions(stageIndex);
  const stageCount = ed.stages.length;
  const set = (patch: Partial<StepDraft>) => ed.updateStep(stageIndex, stepIndex, patch);
  return (
    <div style={styles.stepCard}>
      <input
        style={R.merge(R.inputStyle(), styles.stepName)}
        value={step.name}
        placeholder="step name (slug)"
        aria-label="Step name"
        onChange={(e) => set({ name: e.target.value })}
      />
      <input
        style={R.inputStyle()}
        value={step.title}
        placeholder="Title (worker task title)"
        aria-label="Step title"
        onChange={(e) => set({ title: e.target.value })}
      />
      <textarea
        style={R.merge(R.inputStyle(), styles.textarea)}
        value={step.description}
        placeholder="Description (worker task text)"
        aria-label="Step description"
        rows={2}
        onChange={(e) => set({ description: e.target.value })}
      />
      <details style={styles.details}>
        <summary style={styles.summary}>Overrides</summary>
        <div style={styles.overrideGrid}>
          <input
            style={R.inputStyle()}
            value={step.cwd}
            placeholder="cwd (default)"
            aria-label="Step cwd override"
            onChange={(e) => set({ cwd: e.target.value })}
          />
          <select
            style={R.inputStyle()}
            value={step.coder}
            aria-label="Step coder override"
            onChange={(e) => set({ coder: e.target.value })}
          >
            <option value="">coder (default)</option>
            {ed.coders.map((c) => (
              <option key={c.name} value={c.name}>{c.name}</option>
            ))}
          </select>
          <input
            style={R.inputStyle()}
            value={step.model}
            placeholder="model (default)"
            aria-label="Step model override"
            onChange={(e) => set({ model: e.target.value })}
          />
          <input
            style={R.inputStyle()}
            value={step.priority}
            placeholder="priority (default)"
            aria-label="Step priority override"
            inputMode="numeric"
            onChange={(e) => set({ priority: e.target.value })}
          />
          <select
            style={R.inputStyle()}
            value={step.isolation}
            aria-label="Step isolation override"
            title="Step isolation: inherit the workflow default, run in a worktree, or run in place"
            onChange={(e) => set({ isolation: e.target.value })}
          >
            {ISOLATION_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.value ? `isolation: ${opt.label}` : 'isolation (default)'}
              </option>
            ))}
          </select>
        </div>
      </details>
      <details style={styles.details}>
        <summary style={styles.summary}>Needs</summary>
        {options.length === 0 ? (
          <p style={R.merge(R.mutedStyle(), { margin: 0 })}>
            No earlier steps yet — this step waits for the whole previous stage.
          </p>
        ) : (
          <>
            <p style={R.merge(R.mutedStyle(), { margin: '0 0 0.25rem' })}>
              Unchecked = default: wait for all of the previous stage.
            </p>
            {options.map((dep) => (
              <label key={dep} style={styles.needLabel}>
                <input
                  type="checkbox"
                  checked={step.needs.includes(dep)}
                  onChange={() => ed.toggleNeed(stageIndex, stepIndex, dep)}
                />
                <span style={R.monoStyle()}>{dep}</span>
              </label>
            ))}
          </>
        )}
      </details>
      <div style={styles.cardActions}>
        <button
          style={styles.miniBtn}
          title="Move to the previous stage"
          disabled={stageIndex === 0}
          onClick={() => ed.moveStepAcross(stageIndex, stepIndex, -1)}
        >
          ←
        </button>
        <button
          style={styles.miniBtn}
          title="Move to the next stage"
          disabled={stageIndex === stageCount - 1}
          onClick={() => ed.moveStepAcross(stageIndex, stepIndex, 1)}
        >
          →
        </button>
        <button
          style={styles.miniBtn}
          title="Move up"
          onClick={() => ed.moveStepUpDown(stageIndex, stepIndex, -1)}
        >
          ↑
        </button>
        <button
          style={styles.miniBtn}
          title="Move down"
          onClick={() => ed.moveStepUpDown(stageIndex, stepIndex, 1)}
        >
          ↓
        </button>
        <button
          style={styles.miniBtn}
          title="Duplicate this step"
          onClick={() => ed.duplicateStep(stageIndex, stepIndex)}
        >
          ⧉
        </button>
        <button
          style={styles.miniBtn}
          title="Remove this step"
          onClick={() => ed.removeStep(stageIndex, stepIndex)}
        >
          ✕
        </button>
      </div>
    </div>
  );
}

// One stage column: name, step cards, add/move/remove controls.
function StageColumn({ ed, stageIndex, stage }: { ed: WorkflowEditorState; stageIndex: number; stage: StageDraft }) {
  const empty = stage.steps.length === 0;
  return (
    <div style={styles.stageCol}>
      <div style={styles.stageHead}>
        <input
          style={R.merge(R.inputStyle(), styles.stageName)}
          value={stage.name}
          aria-label={`Stage ${stageIndex + 1} name`}
          onChange={(e) => ed.setStageName(stageIndex, e.target.value)}
        />
        <div style={styles.stageHeadBtns}>
          <button
            style={styles.miniBtn}
            title="Move stage left"
            disabled={stageIndex === 0}
            onClick={() => ed.moveStage(stageIndex, -1)}
          >
            ←
          </button>
          <button
            style={styles.miniBtn}
            title="Move stage right"
            disabled={stageIndex === ed.stages.length - 1}
            onClick={() => ed.moveStage(stageIndex, 1)}
          >
            →
          </button>
          <button
            style={styles.miniBtn}
            title={empty ? 'Remove this stage' : 'Only empty stages can be removed'}
            disabled={!empty}
            onClick={() => ed.removeStage(stageIndex)}
          >
            ✕
          </button>
        </div>
      </div>
      {stage.steps.map((step, stepIndex) => (
        <StepCard key={`${step.name}-${stepIndex}`} ed={ed} stageIndex={stageIndex} stepIndex={stepIndex} step={step} />
      ))}
      <button style={R.merge(T.btnGhost, styles.addBtn)} onClick={() => ed.addStep(stageIndex)}>
        + Add step
      </button>
    </div>
  );
}

// Export panel: read-only YAML with a copy button.
function ExportPanel({ workflowId }: { workflowId: string }) {
  const [yaml, setYaml] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  async function load() {
    setFetching(true);
    setFetchError(null);
    try {
      const result = await api.exportWorkflow(workflowId);
      setYaml(result.yaml);
    } catch (err) {
      setFetchError(errorMessage(err));
    } finally {
      setFetching(false);
    }
  }
  async function copy() {
    if (!yaml) return;
    try {
      await navigator.clipboard.writeText(yaml);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  if (yaml === null) {
    return (
      <span style={styles.exportInline}>
        <button style={T.btnGhost} disabled={fetching} onClick={load}>
          {fetching ? 'Exporting…' : 'Export YAML'}
        </button>
        {fetchError && <span style={styles.exportError}>{fetchError}</span>}
      </span>
    );
  }
  return (
    <span style={styles.exportOpen}>
      <textarea style={R.merge(R.inputStyle(), R.monoStyle(), styles.exportText)} readOnly value={yaml} rows={10} aria-label="Exported workflow YAML" />
      <span style={styles.exportBtns}>
        <button style={T.btnGhost} onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        <button style={T.btnGhost} onClick={() => { setYaml(null); setCopied(false); }}>Close</button>
      </span>
    </span>
  );
}

// The editor form: header, defaults, inputs, stage board, problems, footer.
function WorkflowEditorForm({ initial, onClose, onSaved }: FormProps) {
  const ed = useWorkflowEditor({ initial, onSaved, onClose });
  const isMobile = useIsMobile();
  // Saved workflow waiting for its run form (declared inputs need values).
  const [runTarget, setRunTarget] = useState<Workflow | null>(null);

  // Save first; workflows with inputs open the run form, the rest run now.
  async function handleSaveAndRun() {
    const saved = await ed.save();
    if (!saved) return;
    if ((saved.inputs ?? []).length > 0) setRunTarget(saved);
    else await ed.runNow(saved.id);
  }

  return (
    <div style={R.panelStyle()}>
      <div style={styles.section}>
        <label style={R.fieldLabelStyle()}>
          Name
          <input
            style={R.inputStyle()}
            value={ed.name}
            placeholder="nightly-quality"
            onChange={(e) => ed.setName(e.target.value)}
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Description
          <input
            style={R.inputStyle()}
            value={ed.description}
            placeholder="What this workflow does"
            onChange={(e) => ed.setDescription(e.target.value)}
          />
        </label>
      </div>
      <div style={styles.section}>
        <h3 style={styles.sectionTitle}>Defaults (used when a step leaves a field empty)</h3>
        <div style={styles.defaultsRow}>
          <label style={R.fieldLabelStyle()}>
            cwd
            <input
              style={R.inputStyle()}
              value={ed.defCwd}
              placeholder="/path/to/repo"
              onChange={(e) => ed.setDefCwd(e.target.value)}
            />
          </label>
          <label style={R.fieldLabelStyle()}>
            coder
            <select style={R.inputStyle()} value={ed.defCoder} onChange={(e) => ed.handleCoderChange(e.target.value)}>
              <option value="">—</option>
              {ed.coders.map((c) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </label>
          <label style={R.fieldLabelStyle()}>
            model
            <input
              style={R.inputStyle()}
              value={ed.defModel}
              placeholder="model"
              onChange={(e) => ed.setDefModel(e.target.value)}
            />
          </label>
          <label style={R.fieldLabelStyle()}>
            priority
            <input
              style={R.inputStyle()}
              value={ed.defPriority}
              placeholder="2"
              inputMode="numeric"
              onChange={(e) => ed.setDefPriority(e.target.value)}
            />
          </label>
          <label style={R.fieldLabelStyle()}>
            isolation
            <select
              style={R.inputStyle()}
              value={ed.defIsolation}
              title="Default isolation for steps that leave it empty: inherit, worktree, or run in place"
              onChange={(e) => ed.setDefIsolation(e.target.value)}
            >
              {ISOLATION_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div style={styles.section}>
        <h3 style={styles.sectionTitle}>Inputs (values the operator passes when starting a run)</h3>
        {ed.inputs.length === 0 ? (
          <p style={R.merge(R.mutedStyle(), { margin: 0 })}>
            No inputs — every run does the same thing. Steps can use
            <span style={R.monoStyle()}> {'{{inputs.<name>}}'} </span>
            placeholders once an input exists.
          </p>
        ) : (
          ed.inputs.map((row, i) => (
            <div key={i} style={styles.inputRow}>
              <input
                style={R.merge(R.inputStyle(), styles.inputName)}
                value={row.name}
                placeholder="name (slug)"
                aria-label={`Input ${i + 1} name`}
                onChange={(e) => ed.updateInput(i, { name: e.target.value })}
              />
              <input
                style={R.merge(R.inputStyle(), styles.inputDesc)}
                value={row.description}
                placeholder="description (shown in the run form)"
                aria-label={`Input ${i + 1} description`}
                onChange={(e) => ed.updateInput(i, { description: e.target.value })}
              />
              <input
                style={R.merge(R.inputStyle(), styles.inputDefault)}
                value={row.default}
                placeholder="default"
                aria-label={`Input ${i + 1} default`}
                onChange={(e) => ed.updateInput(i, { default: e.target.value })}
              />
              <label style={styles.requiredLabel} title="Required inputs have no default and must be filled at run start">
                <input
                  type="checkbox"
                  checked={row.required}
                  aria-label={`Input ${i + 1} required`}
                  onChange={(e) => ed.updateInput(i, { required: e.target.checked })}
                />
                required
              </label>
              <button
                style={styles.miniBtn}
                title="Remove this input"
                aria-label={`Remove input ${i + 1}`}
                onClick={() => ed.removeInput(i)}
              >
                ✕
              </button>
            </div>
          ))
        )}
        <div>
          <button style={R.merge(T.btnGhost, styles.addBtn)} onClick={ed.addInput}>
            + Add input
          </button>
        </div>
      </div>
      <div style={styles.section}>
        <p style={R.mutedStyle()}>
          Steps in the same stage run in parallel. A stage starts when the previous one is complete.{' '}
          <span title="A step with no Needs waits for every step of the previous stage. Tick Needs to wait for only some earlier steps (a fast lane); Needs can only point at earlier stages.">
            (?)
          </span>
        </p>
        <div style={R.merge(styles.board, isMobile ? styles.boardMobile : {})}>
          {ed.stages.map((stage, i) => (
            <StageColumn key={`${stage.name}-${i}`} ed={ed} stageIndex={i} stage={stage} />
          ))}
          <button style={R.merge(T.btnGhost, styles.addStageBtn)} onClick={ed.addStage}>
            + Add stage
          </button>
        </div>
      </div>
      <div style={styles.section}>
        <h3 style={styles.sectionTitle}>
          Problems{ed.validating ? ' (checking…)' : ''}
        </h3>
        {ed.problems.length === 0 ? (
          <p style={R.merge(R.mutedStyle(), { margin: 0 })}>No problems — the workflow is ready to save.</p>
        ) : (
          <ul style={styles.problems}>
            {ed.problems.map((problem) => (
              <li key={problem} style={styles.problem}>{problem}</li>
            ))}
          </ul>
        )}
        {ed.error && <p style={R.errorMsgStyle()}>Save failed: {errorMessage(ed.error)}</p>}
      </div>
      <div style={styles.footer}>
        <button
          style={R.merge(T.btnPrimary, ed.canSubmit ? {} : styles.disabledBtn)}
          disabled={!ed.canSubmit}
          title={ed.canSubmit ? 'Save the workflow' : 'Resolve the problems above first'}
          onClick={() => void ed.save()}
        >
          Save
        </button>
        <button
          style={R.merge(T.btnGhost, ed.canSubmit ? {} : styles.disabledBtn)}
          disabled={!ed.canSubmit}
          title={ed.canSubmit ? 'Save and start a run' : 'Resolve the problems above first'}
          onClick={() => void handleSaveAndRun()}
        >
          Save and run
        </button>
        <button style={T.btnGhost} onClick={ed.onClose}>Cancel</button>
        <span style={styles.exportWrap}>
          {initial ? (
            <ExportPanel workflowId={initial.id} />
          ) : (
            <span title="Save first">
              <button style={R.merge(T.btnGhost, styles.disabledBtn)} disabled>Export YAML</button>
            </span>
          )}
        </span>
      </div>
      {runTarget && (
        <RunWorkflowModal
          workflow={runTarget}
          onClose={() => setRunTarget(null)}
        />
      )}
    </div>
  );
}

const styles = {
  section: {
    padding: '0.875rem 1rem', borderBottom: `1px solid ${T.colors.borderSubtle}`,
    display: 'flex', flexDirection: 'column' as const, gap: '0.625rem',
  } as React.CSSProperties,
  sectionTitle: {
    margin: 0, fontSize: '0.8125rem', fontWeight: 600, color: T.colors.textSecondary,
  } as React.CSSProperties,
  defaultsRow: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(10rem, 1fr))', gap: '0.625rem',
  } as React.CSSProperties,
  board: {
    display: 'flex', gap: '0.75rem', overflowX: 'auto' as const,
    paddingBottom: '0.5rem', alignItems: 'flex-start',
  } as React.CSSProperties,
  boardMobile: { flexDirection: 'column' as const, overflowX: 'visible' as const } as React.CSSProperties,
  stageCol: {
    minWidth: '17rem', maxWidth: '17rem', flexShrink: 0,
    background: T.colors.bgDeep, border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '0.375rem', padding: '0.625rem', display: 'flex',
    flexDirection: 'column' as const, gap: '0.5rem',
  } as React.CSSProperties,
  stageHead: { display: 'flex', gap: '0.375rem', alignItems: 'center' } as React.CSSProperties,
  stageName: { flex: 1, minWidth: 0, fontWeight: 600 } as React.CSSProperties,
  stageHeadBtns: { display: 'inline-flex', gap: '0.25rem' } as React.CSSProperties,
  stepCard: {
    background: T.colors.bgElevated, border: `1px solid ${T.colors.border}`,
    borderRadius: '0.375rem', padding: '0.5rem', display: 'flex',
    flexDirection: 'column' as const, gap: '0.375rem',
  } as React.CSSProperties,
  stepName: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' } as React.CSSProperties,
  textarea: { resize: 'vertical' as const } as React.CSSProperties,
  details: { fontSize: '0.8125rem', color: T.colors.textSecondary } as React.CSSProperties,
  summary: { cursor: 'pointer', fontWeight: 600 } as React.CSSProperties,
  overrideGrid: {
    display: 'flex', flexDirection: 'column' as const, gap: '0.375rem', marginTop: '0.375rem',
  } as React.CSSProperties,
  needLabel: {
    display: 'flex', alignItems: 'center', gap: '0.375rem',
    fontSize: '0.8125rem', color: T.colors.textPrimary, padding: '0.1rem 0',
  } as React.CSSProperties,
  inputRow: {
    display: 'flex', gap: '0.375rem', alignItems: 'center', flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  inputName: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    flex: '0 1 10rem', minWidth: '8rem',
  } as React.CSSProperties,
  inputDesc: { flex: '2 1 14rem', minWidth: '10rem' } as React.CSSProperties,
  inputDefault: { flex: '1 1 8rem', minWidth: '6rem' } as React.CSSProperties,
  requiredLabel: {
    display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
    fontSize: '0.8125rem', color: T.colors.textSecondary, cursor: 'pointer',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  cardActions: { display: 'flex', gap: '0.25rem' } as React.CSSProperties,
  miniBtn: {
    ...T.btnGhost, padding: '0.1rem 0.45rem', fontSize: '0.8125rem', lineHeight: 1.4,
  } as React.CSSProperties,
  addBtn: { fontSize: '0.8125rem', padding: '0.3rem 0.625rem' } as React.CSSProperties,
  addStageBtn: {
    minWidth: '8rem', alignSelf: 'flex-start', fontSize: '0.8125rem', padding: '0.4rem 0.875rem',
  } as React.CSSProperties,
  problems: {
    margin: 0, paddingLeft: '1.25rem', color: T.colors.danger, fontSize: '0.8125rem',
    display: 'flex', flexDirection: 'column' as const, gap: '0.25rem',
  } as React.CSSProperties,
  problem: {} as React.CSSProperties,
  footer: {
    display: 'flex', gap: '0.5rem', alignItems: 'center',
    padding: '0.875rem 1rem', flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  disabledBtn: { opacity: 0.4, cursor: 'not-allowed' as const } as React.CSSProperties,
  exportWrap: { marginLeft: 'auto' } as React.CSSProperties,
  exportInline: { display: 'inline-flex', alignItems: 'center', gap: '0.5rem' } as React.CSSProperties,
  exportOpen: {
    display: 'flex', flexDirection: 'column' as const, gap: '0.375rem',
    flexBasis: '100%', marginTop: '0.5rem',
  } as React.CSSProperties,
  exportError: { fontSize: '0.8125rem', color: T.colors.danger } as React.CSSProperties,
  exportText: { width: '100%', resize: 'vertical' as const, fontSize: '0.75rem' } as React.CSSProperties,
  exportBtns: { display: 'inline-flex', gap: '0.375rem' } as React.CSSProperties,
};
