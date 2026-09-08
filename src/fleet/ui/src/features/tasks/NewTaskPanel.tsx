/**
 * Modal form for creating a task.
 * Thin shell over useNewTaskForm: header, fields, templates and
 * actions. Called by App when the new-task button fires.
 */
import * as R from '../../shared/styles/recipes';
import { useNewTaskForm } from './hooks/useNewTaskForm';
import { CoderModelPriority, DepsAndArgs, TemplatePicker } from './NewTaskOptions';
import { styles } from './newTaskPanelStyles';

interface Props {
  onClose: () => void;
  onCreated: (id: string) => void;
}

// New-task modal; all state lives in useNewTaskForm.
export function NewTaskPanel({ onClose, onCreated }: Props) {
  const f = useNewTaskForm(onClose, onCreated);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    void f.submit();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void f.submit();
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.panel} onClick={(e) => e.stopPropagation()}>
        <div style={styles.header}>
          <h2 style={styles.heading}>New task</h2>
          <button style={styles.closeBtn} onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit} onKeyDown={handleKeyDown} style={styles.form}>
          <label style={R.fieldLabelStyle()}>
            Title *
            <input
              style={R.merge(styles.input, R.when(!!f.titleError, styles.inputError))}
              value={f.title}
              onChange={(e) => f.setTitle(e.target.value)}
              placeholder="What should this task do?"
              autoFocus
            />
            {f.titleError && <span style={styles.errorMsg}>{f.titleError}</span>}
          </label>
          <label style={R.fieldLabelStyle()}>
            Description
            <textarea
              style={R.merge(styles.input, styles.textarea)}
              value={f.description}
              onChange={(e) => f.setDescription(e.target.value)}
              placeholder="Markdown description (optional)"
              rows={4}
            />
          </label>
          <label style={R.fieldLabelStyle()}>
            Working directory
            <input
              style={styles.input}
              value={f.cwd}
              onChange={(e) => f.setCwd(e.target.value)}
              list="cwd-options"
              placeholder="/path/to/project"
            />
            <datalist id="cwd-options">
              {f.recentCwds.map((c) => <option key={c} value={c} />)}
            </datalist>
          </label>
          <CoderModelPriority f={f} />
          <DepsAndArgs f={f} />
          <TemplatePicker templates={f.templates} onPick={f.applyTemplate} />
          <div style={styles.actions}>
            {f.createTask.error && (
              <span style={styles.errorMsg}>{(f.createTask.error as Error).message}</span>
            )}
            <button type="button" style={styles.cancelBtn} onClick={onClose}>
              Cancel
            </button>
            <button type="submit" style={styles.submitBtn} disabled={f.createTask.isPending}>
              {f.createTask.isPending ? 'Creating…' : 'Create task'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
