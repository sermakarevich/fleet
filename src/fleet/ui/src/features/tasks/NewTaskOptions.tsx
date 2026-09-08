/**
 * Field groups for the new-task modal: coder/model/priority row,
 * dependencies, extra args and the template picker.
 * Called by NewTaskPanel; state comes from useNewTaskForm.
 */
import * as R from '../../shared/styles/recipes';
import type { Template } from '../../shared/types';
import type { NewTaskForm } from './hooks/useNewTaskForm';
import { styles } from './newTaskPanelStyles';

// Coder, model and priority inputs side by side.
export function CoderModelPriority({ f }: { f: NewTaskForm }) {
  return (
    <div style={styles.row}>
      <label style={R.merge(styles.label, styles.grow)}>
        Coder
        <select style={styles.input} value={f.coder} onChange={(e) => f.handleCoderChange(e.target.value)}>
          <option value="">— default —</option>
          {f.coders.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name} ({Math.round(c.context_limit / 1000)}k) — {c.default_model}
            </option>
          ))}
        </select>
      </label>
      <label style={R.merge(styles.label, styles.grow)}>
        Model
        <input style={styles.input} value={f.model} onChange={(e) => f.setModel(e.target.value)} placeholder="default" />
      </label>
      <label style={R.merge(styles.label, styles.prio)}>
        Priority
        <input style={styles.input} type="number" value={f.priority} onChange={(e) => f.setPriority(e.target.value)} placeholder="0" min={0} />
      </label>
    </div>
  );
}

// Dependencies multi-select plus extra args input.
export function DepsAndArgs({ f }: { f: NewTaskForm }) {
  return (
    <>
      {f.openTasks.length > 0 && (
        <label style={R.fieldLabelStyle()}>
          Dependencies
          <select
            multiple
            style={R.merge(styles.input, styles.multiSelect)}
            value={f.dependencies}
            onChange={(e) => f.setDependencies(Array.from(e.target.selectedOptions, (o) => o.value))}
          >
            {f.openTasks.map((t) => (
              <option key={t.id} value={t.id}>{t.id} — {t.title}</option>
            ))}
          </select>
          <span style={styles.hint}>Hold Ctrl/⌘ to select multiple</span>
        </label>
      )}
      <label style={R.fieldLabelStyle()}>
        Extra args
        <input style={styles.input} value={f.args} onChange={(e) => f.setArgs(e.target.value)} placeholder="--deps fleet-abc,fleet-xyz --type feature" />
      </label>
    </>
  );
}

// Buttons applying a template to the title/description.
export function TemplatePicker({ templates, onPick }: { templates: Template[]; onPick: (t: Template) => void }) {
  if (templates.length === 0) return null;
  return (
    <div style={styles.templateSection}>
      <p style={styles.templateLabel}>Templates</p>
      <div style={styles.templateList}>
        {templates.map((t) => (
          <button key={t.name} type="button" style={styles.templateBtn} onClick={() => onPick(t)}>
            {t.name}
          </button>
        ))}
      </div>
    </div>
  );
}
