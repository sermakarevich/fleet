/**
 * Modal form for creating a worker: either run now (POST /api/tasks) or
 * on a schedule (POST /api/schedules with target=task, same worker
 * fields as the schedule payload). Thin shell over useNewWorkerForm:
 * header, fields, schedule switch, templates and actions. Called by App
 * when the new-worker button fires.
 */
import * as R from '../../shared/styles/recipes';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { Modal } from '../../shared/ui/Modal';
import { CRON_PRESETS } from '../triggers/cronPresets';
import { useNewWorkerForm } from './hooks/useNewWorkerForm';
import { CoderModelPriority, DepsAndArgs, TemplatePicker } from './NewWorkerOptions';
import { styles } from './newWorkerPanelStyles';

interface Props {
  onClose: () => void;
  onCreated: (id: string) => void;
}

// Schedule-only fields: name, cron + preset picker, timezone, overlap.
function ScheduleFields({ f }: { f: ReturnType<typeof useNewWorkerForm> }) {
  const previewTimes = f.cronPreview.data?.upcoming ?? [];
  const previewError = f.cronPreview.data && !f.cronPreview.data.valid
    ? (f.cronPreview.data.error ?? 'Invalid cron expression')
    : null;
  return (
    <>
      <label style={R.fieldLabelStyle()}>
        Schedule name
        <input
          style={styles.input}
          value={f.scheduleName}
          onChange={(e) => f.setScheduleName(e.target.value)}
          placeholder="Defaults to the title"
        />
      </label>
      <label style={R.fieldLabelStyle()}>
        Cron *
        <input
          style={R.merge(styles.input, styles.mono)}
          value={f.cron}
          onChange={(e) => f.setCron(e.target.value)}
          placeholder="0 9 * * 1-5"
          spellCheck={false}
        />
      </label>
      <label style={R.fieldLabelStyle()}>
        Preset
        <select
          style={styles.input}
          value=""
          onChange={(e) => { if (e.target.value) f.applyPreset(e.target.value); }}
          aria-label="Cron preset"
        >
          <option value="">— pick a preset —</option>
          {CRON_PRESETS.map((p) => (
            <option key={p.expression} value={p.expression}>
              {p.label} ({p.expression})
            </option>
          ))}
        </select>
      </label>
      {f.cronPreview.isFetching && <p style={R.mutedStyle()}>Checking schedule…</p>}
      {previewError && <p style={styles.errorMsg}>{previewError}</p>}
      {f.cronValid && previewTimes.length > 0 && (
        <p style={R.mutedStyle()}>Next: {previewTimes.slice(0, 3).map(fmtTs).join(', ')}</p>
      )}
      <div style={styles.row}>
        <label style={R.merge(R.fieldLabelStyle(), styles.grow)}>
          Timezone
          <input
            style={styles.input}
            value={f.timezone}
            onChange={(e) => f.setTimezone(e.target.value)}
            placeholder="Europe/Warsaw"
            spellCheck={false}
          />
        </label>
        <label style={R.merge(R.fieldLabelStyle(), styles.grow)}>
          Overlap
          <select style={styles.input} value={f.overlap} onChange={(e) => f.setOverlap(e.target.value)}>
            <option value="skip">skip</option>
            <option value="queue">queue</option>
          </select>
        </label>
      </div>
      {f.scheduleError && <span style={styles.errorMsg}>{f.scheduleError}</span>}
    </>
  );
}

// New-worker modal; all state lives in useNewWorkerForm.
export function NewWorkerPanel({ onClose, onCreated }: Props) {
  const f = useNewWorkerForm(onClose, onCreated);

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

  const submitError = (f.createTask.error ?? f.createSchedule.error) as Error | null;
  const submitLabel = f.pending
    ? (f.mode === 'schedule' ? 'Creating…' : 'Creating…')
    : (f.mode === 'schedule' ? 'Create schedule' : 'Create worker');

  return (
    <Modal labelledBy="new-worker-title" onClose={onClose} panelStyle={styles.panel}>
        <div style={styles.header}>
          <h2 id="new-worker-title" style={styles.heading}>New worker</h2>
          <button style={styles.closeBtn} onClick={onClose} aria-label="Close">×</button>
        </div>
        {/* Form-wide Cmd/Ctrl+Enter shortcut: every field stays natively
            keyboard-operable, so this needs no tab stop or role of its own. */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
        <form onSubmit={handleSubmit} onKeyDown={handleKeyDown} style={styles.form}>
          <label style={R.fieldLabelStyle()}>
            Title *
            <input
              style={R.merge(styles.input, R.when(!!f.titleError, styles.inputError))}
              value={f.title}
              onChange={(e) => f.setTitle(e.target.value)}
              placeholder="What should this worker do?"
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
          <fieldset style={styles.runSwitch}>
            <legend style={styles.runLegend}>Run</legend>
            <label style={styles.runOption}>
              <input
                type="radio"
                name="run-mode"
                checked={f.mode === 'now'}
                onChange={() => f.setMode('now')}
              />
              now
            </label>
            <label style={styles.runOption}>
              <input
                type="radio"
                name="run-mode"
                checked={f.mode === 'schedule'}
                onChange={() => f.setMode('schedule')}
              />
              on a schedule
            </label>
          </fieldset>
          {f.mode === 'schedule' && <ScheduleFields f={f} />}
          <TemplatePicker templates={f.templates} onPick={f.applyTemplate} />
          <div style={styles.actions}>
            {submitError && (
              <span style={styles.errorMsg}>{submitError.message}</span>
            )}
            <button type="button" style={styles.cancelBtn} onClick={onClose}>
              Cancel
            </button>
            <button type="submit" style={styles.submitBtn} disabled={f.pending}>
              {submitLabel}
            </button>
          </div>
        </form>
    </Modal>
  );
}
