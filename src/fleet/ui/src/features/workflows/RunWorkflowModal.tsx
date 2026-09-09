/**
 * Run form for one workflow: one field per declared input, opened by the
 * Run button when the workflow declares `inputs` (workflows without
 * inputs run immediately with no modal). Defaults pre-fill their fields;
 * Run stays disabled until every required input has a value; a 422 from
 * the server shows inline. Called by WorkflowsPage and WorkflowEditor.
 */
import { useState } from 'react';
import { api, errorMessage } from '../../shared/api';
import { useRunWorkflow } from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import type { Workflow } from '../../shared/types';
import { Modal } from '../../shared/ui/Modal';

interface Props {
  workflow: Workflow;
  onClose: () => void;
  onStarted?: (runId: string) => void;
}

// Initial field values: each declared default, else empty.
function initialValues(workflow: Workflow): Record<string, string> {
  const values: Record<string, string> = {};
  for (const input of workflow.inputs ?? []) {
    values[input.name] = input.default ?? '';
  }
  return values;
}

// Run form modal: label = input name, help = description, * = required.
export function RunWorkflowModal({ workflow, onClose, onStarted }: Props) {
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(workflow));
  const runWorkflow = useRunWorkflow();
  const inputs = workflow.inputs ?? [];

  function setValue(name: string, value: string) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  const missing = inputs.filter(
    (input) => input.required && !(values[input.name] ?? '').trim(),
  );
  const canRun = missing.length === 0 && !runWorkflow.isPending;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canRun) return;
    try {
      const result = await runWorkflow.mutateAsync({ id: workflow.id, inputs: values });
      onStarted?.(result.run.id);
      onClose();
    } catch {
      // The failure toasts via the mutation; the 422 text also shows inline.
    }
  }

  return (
    <Modal labelledBy="run-workflow-title" onClose={onClose} panelStyle={styles.panel}>
      <div style={styles.header}>
        <h2 id="run-workflow-title" style={styles.heading}>
          Run {workflow.name}
        </h2>
        <button style={styles.closeBtn} onClick={onClose} aria-label="Close">×</button>
      </div>
      <form onSubmit={handleSubmit} style={styles.form}>
        {inputs.map((input) => (
          <label key={input.name} style={R.fieldLabelStyle()}>
            <span>
              <span style={R.monoStyle()}>{input.name}</span>
              {input.required && <span style={styles.required}> *</span>}
            </span>
            <input
              style={R.inputStyle()}
              value={values[input.name] ?? ''}
              placeholder={input.default ?? ''}
              aria-label={input.required ? `${input.name} (required)` : input.name}
              onChange={(e) => setValue(input.name, e.target.value)}
            />
            {input.description && <span style={styles.hint}>{input.description}</span>}
          </label>
        ))}
        {runWorkflow.error && (
          <p style={styles.inlineError} role="alert">
            {errorMessage(runWorkflow.error)}
          </p>
        )}
        <div style={styles.actions}>
          <button type="button" style={styles.cancelBtn} onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            style={R.merge(T.btnPrimary, R.when(!canRun, styles.submitDisabled))}
            disabled={!canRun}
            title={canRun ? 'Start a run of this workflow' : 'Fill in every required input first'}
          >
            {runWorkflow.isPending ? 'Starting…' : 'Run'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// Re-exported for tests: the API call the modal makes.
export async function startRunWithInputs(
  workflowId: string,
  values: Record<string, string>,
): Promise<string> {
  const result = await api.runWorkflow(workflowId, values);
  return result.run.id;
}

const styles = {
  panel: {
    ...T.panel, width: '100%', maxWidth: '28rem',
    maxHeight: 'calc(100vh - 8rem)', overflowY: 'auto', fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '1rem 1.25rem 0.75rem', borderBottom: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  heading: {
    margin: 0, fontSize: '0.9375rem', fontWeight: 600, color: T.colors.textPrimary,
  } as React.CSSProperties,
  closeBtn: {
    background: 'none', border: 'none', color: T.colors.textDim,
    cursor: 'pointer', fontSize: '1.25rem', lineHeight: 1, padding: '0 0.25rem',
  } as React.CSSProperties,
  form: {
    padding: '1rem 1.25rem', display: 'flex',
    flexDirection: 'column' as const, gap: '0.875rem',
  } as React.CSSProperties,
  required: { color: T.colors.danger, fontWeight: 700 } as React.CSSProperties,
  hint: {
    fontSize: '0.6875rem', color: T.colors.textDim,
  } as React.CSSProperties,
  inlineError: {
    margin: 0, fontSize: '0.8125rem', color: T.colors.danger,
  } as React.CSSProperties,
  actions: {
    display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
    gap: '0.75rem', paddingTop: '0.5rem', borderTop: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  cancelBtn: {
    ...T.btnGhost, padding: '0.4rem 0.875rem', fontSize: '0.875rem',
  } as React.CSSProperties,
  submitDisabled: {
    opacity: 0.45, cursor: 'default',
  } as React.CSSProperties,
};
