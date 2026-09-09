/**
 * Modal form for creating or editing a schedule.
 * Thin shell over useScheduleForm: fields, preset picker, live cron
 * preview and actions. Called by SchedulesPage (create) and
 * ScheduleDrawer (edit).
 */
import * as R from '../../shared/styles/recipes';
import * as T from '../../shared/styles/tokens';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { Modal } from '../../shared/ui/Modal';
import { CRON_PRESETS } from './cronPresets';
import { useScheduleForm } from './useScheduleForm';
import type { Schedule } from '../../shared/types';

interface Props {
  initial?: Schedule | null;
  onClose: () => void;
  onSaved: (schedule: Schedule) => void;
}

// Schedule create/edit modal; all state lives in useScheduleForm.
export function ScheduleForm({ initial, onClose, onSaved }: Props) {
  const f = useScheduleForm({ initial, onSaved, onClose });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    void f.submit();
  }

  const previewTimes = f.preview.data?.upcoming ?? [];
  const previewError = f.preview.data && !f.preview.data.valid ? (f.preview.data.error ?? 'Invalid cron expression') : null;

  return (
    <Modal labelledBy="schedule-form-title" onClose={onClose} panelStyle={styles.panel}>
      <div style={styles.header}>
        <h2 id="schedule-form-title" style={styles.heading}>{f.isEdit ? 'Edit schedule' : 'New schedule'}</h2>
        <button style={styles.closeBtn} onClick={onClose} aria-label="Close">×</button>
      </div>
      <form onSubmit={handleSubmit} style={styles.form}>
        <label style={R.fieldLabelStyle()}>
          Name *
          <input
            style={R.inputStyle()}
            value={f.name}
            onChange={(e) => f.setName(e.target.value)}
            placeholder="nightly-triage"
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Cron *
          <input
            style={R.merge(R.inputStyle(), R.monoStyle())}
            value={f.cron}
            onChange={(e) => f.setCron(e.target.value)}
            placeholder="0 9 * * 1-5"
            spellCheck={false}
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Preset
          <select
            style={R.inputStyle()}
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
        {f.preview.isFetching && <p style={R.mutedStyle()}>Checking schedule…</p>}
        {previewError && <p style={styles.previewError}>{previewError}</p>}
        {f.cronValid && previewTimes.length > 0 && (
          <p style={R.mutedStyle()}>Next: {previewTimes.slice(0, 3).map(fmtTs).join(', ')}</p>
        )}
        <label style={R.fieldLabelStyle()}>
          Timezone
          <input
            style={R.inputStyle()}
            value={f.timezone}
            onChange={(e) => f.setTimezone(e.target.value)}
            placeholder="Europe/Warsaw"
            spellCheck={false}
          />
        </label>
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
        <label style={R.fieldLabelStyle()}>
          Overlap
          <select style={R.inputStyle()} value={f.overlap} onChange={(e) => f.setOverlap(e.target.value)}>
            <option value="skip">skip</option>
            <option value="queue">queue</option>
          </select>
          <span style={styles.hint}>
            {f.overlap === 'queue'
              ? 'queue: always open a new task, even if the previous run is still open.'
              : 'skip: skip the firing when the previous run\u2019s task is still open.'}
          </span>
        </label>
        <label style={styles.checkRow}>
          <input type="checkbox" checked={f.enabled} onChange={(e) => f.setEnabled(e.target.checked)} />
          Enabled
        </label>
        <div style={styles.actions}>
          {f.error && <span style={styles.errorMsg}>{(f.error as Error).message}</span>}
          <button type="button" style={styles.cancelBtn} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" style={R.merge(T.btnPrimary, R.when(!f.canSubmit, styles.submitDisabled))} disabled={!f.canSubmit}>
            {f.pending ? 'Saving…' : f.isEdit ? 'Save changes' : 'Create schedule'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const styles = {
  panel: {
    ...T.panel, width: '100%', maxWidth: '36rem',
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
  textarea: {
    fontFamily: 'ui-monospace, monospace', resize: 'vertical' as const,
  } as React.CSSProperties,
  hint: {
    fontSize: '0.6875rem', color: T.colors.textDim,
  } as React.CSSProperties,
  row: {
    display: 'flex', gap: '0.75rem',
  } as React.CSSProperties,
  grow: { flex: 1 } as React.CSSProperties,
  prio: { width: '6rem' } as React.CSSProperties,
  checkRow: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
    fontSize: '0.875rem', color: T.colors.textSecondary, cursor: 'pointer',
  } as React.CSSProperties,
  actions: {
    display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
    gap: '0.75rem', paddingTop: '0.5rem', borderTop: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  errorMsg: {
    color: T.colors.danger, fontSize: '0.75rem', flex: 1,
  } as React.CSSProperties,
  cancelBtn: {
    ...T.btnGhost, padding: '0.4rem 0.875rem', fontSize: '0.875rem',
  } as React.CSSProperties,
  previewError: {
    margin: 0, fontSize: '0.8125rem', color: T.colors.danger,
  } as React.CSSProperties,
  submitDisabled: {
    opacity: 0.45, cursor: 'default',
  } as React.CSSProperties,
};
