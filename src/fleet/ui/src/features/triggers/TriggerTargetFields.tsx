// Target-specific fields for the trigger form: the worker template
// fields (title, description, cwd, coder/model/priority) for task
// schedules, or the workflow picker for workflow schedules.
// Rendered by TriggerForm; all state lives in useTriggerForm.
import * as R from '../../shared/styles/recipes';
import * as T from '../../shared/styles/tokens';
import { useTriggerForm, workflowOptionLabel } from './useTriggerForm';

// Worker fields for a task-target schedule.
function TaskFields({ f }: { f: ReturnType<typeof useTriggerForm> }) {
  return (
    <>
      <label style={R.fieldLabelStyle()}>
        Task title template *
        <input
          style={R.inputStyle()}
          value={f.title}
          onChange={(e) => f.setTitle(e.target.value)}
          placeholder="Triage inbox {date}"
        />
        <span style={styles.hint}>Placeholders: {'{name} {date} {time} {n}'}</span>
      </label>
      <label style={R.fieldLabelStyle()}>
        Task description template
        <textarea
          style={R.merge(R.inputStyle(), styles.textarea)}
          value={f.description}
          onChange={(e) => f.setDescription(e.target.value)}
          placeholder="Markdown body for each run's task (optional)"
          rows={4}
        />
      </label>
      <label style={R.fieldLabelStyle()}>
        Working directory
        <input
          style={R.inputStyle()}
          value={f.cwd}
          onChange={(e) => f.setCwd(e.target.value)}
          placeholder="/path/to/project"
        />
      </label>
      <div style={styles.row}>
        <label style={R.merge(R.fieldLabelStyle(), styles.grow)}>
          Coder
          <select style={R.inputStyle()} value={f.coder} onChange={(e) => f.handleCoderChange(e.target.value)}>
            <option value="">— default —</option>
            {f.coders.map((c) => (
              <option key={c.name} value={c.name}>{c.name}</option>
            ))}
          </select>
        </label>
        <label style={R.merge(R.fieldLabelStyle(), styles.grow)}>
          Model
          <input
            style={R.inputStyle()}
            value={f.model}
            onChange={(e) => f.setModel(e.target.value)}
            placeholder="default"
          />
        </label>
        <label style={R.merge(R.fieldLabelStyle(), styles.prio)}>
          Priority
          <select style={R.inputStyle()} value={f.priority} onChange={(e) => f.setPriority(Number(e.target.value))}>
            {[0, 1, 2, 3, 4].map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
      </div>
    </>
  );
}

// Workflow picker for a workflow-target schedule; picking defaults the
// schedule name to the workflow name when the name is still blank.
function WorkflowField({ f }: { f: ReturnType<typeof useTriggerForm> }) {
  return (
    <label style={R.fieldLabelStyle()}>
      Workflow *
      <select
        style={R.inputStyle()}
        value={f.workflowId}
        onChange={(e) => f.handleWorkflowChange(e.target.value)}
        aria-label="Workflow"
      >
        <option value="">— pick a workflow —</option>
        {f.workflows.map((w) => (
          <option key={w.id} value={w.id}>
            {workflowOptionLabel(w)}
          </option>
        ))}
      </select>
    </label>
  );
}

// One field per input the picked workflow declares: typed values win,
// declared defaults fill the rest at submit time.
function WorkflowInputsFields({ f }: { f: ReturnType<typeof useTriggerForm> }) {
  if (f.decls.length === 0) return null;
  return (
    <>
      {f.decls.map((decl) => (
        <label key={decl.name} style={R.fieldLabelStyle()}>
          <span>
            <span style={R.monoStyle()}>{decl.name}</span>
            {decl.required && <span style={styles.required}> *</span>}
          </span>
          <input
            style={R.inputStyle()}
            value={f.inputValue(decl.name, decl.default)}
            placeholder={decl.default ?? ''}
            aria-label={decl.required ? `${decl.name} (required)` : decl.name}
            onChange={(e) => f.setInput(decl.name, e.target.value)}
          />
          {decl.description && <span style={styles.hint}>{decl.description}</span>}
        </label>
      ))}
    </>
  );
}

// Task fields or workflow picker, chosen by the form's target.
export function TriggerTargetFields({
  f, target, slot,
}: {
  f: ReturnType<typeof useTriggerForm>; target: 'task' | 'workflow'; slot: 'top' | 'mid';
}) {
  if (target === 'workflow') {
    if (slot === 'top') return <WorkflowField f={f} />;
    return <WorkflowInputsFields f={f} />;
  }
  return slot === 'mid' ? <TaskFields f={f} /> : null;
}

const styles = {
  hint: { fontSize: '0.6875rem', color: T.colors.textDim } as React.CSSProperties,
  required: { color: T.colors.danger, fontWeight: 700 } as React.CSSProperties,
  textarea: {
    fontFamily: 'ui-monospace, monospace', resize: 'vertical' as const,
  } as React.CSSProperties,
  row: { display: 'flex', gap: '0.75rem' } as React.CSSProperties,
  grow: { flex: 1 } as React.CSSProperties,
  prio: { width: '6rem' } as React.CSSProperties,
};
