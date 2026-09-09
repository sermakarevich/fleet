/**
 * Modal form for creating or editing a trigger (a schedule), for either
 * target. Thin shell over useTriggerForm: shared name/cron/preset/timezone
 * fields, the target-specific fields, overlap, enabled and actions.
 * Called by TriggerTable (create) and TriggerDrawer (edit).
 */
import * as R from '../../shared/styles/recipes';
import * as T from '../../shared/styles/tokens';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { Modal } from '../../shared/ui/Modal';
import type { Schedule } from '../../shared/types';
import { CRON_PRESETS } from './cronPresets';
import type { TriggerTarget } from './types';
import { useTriggerForm } from './useTriggerForm';
import { TriggerTargetFields } from './TriggerTargetFields';

interface Props {
  target: TriggerTarget;
  initial?: Schedule | null;
  onClose: () => void;
  onSaved: (schedule: Schedule) => void;
}

// Heading per target and mode: four combinations from one table.
const HEADINGS: Record<TriggerTarget, { create: string; edit: string }> = {
  task: { create: 'New schedule', edit: 'Edit schedule' },
  workflow: { create: 'Schedule a workflow', edit: 'Edit recurring workflow' },
};

// Trigger create/edit modal; all state lives in useTriggerForm.
export function TriggerForm({ target, initial, onClose, onSaved }: Props) {
  const f = useTriggerForm({ target, initial, onSaved, onClose });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    void f.submit();
  }

  const previewTimes = f.preview.data?.upcoming ?? [];
  const previewError = f.preview.data && !f.preview.data.valid
    ? (f.preview.data.error ?? 'Invalid cron expression')
    : null;
  const heading = f.isEdit ? HEADINGS[target].edit : HEADINGS[target].create;
  const overlapHint = target === 'workflow'
    ? (f.overlap === 'queue'
      ? 'queue: always start a new run, even if the previous one is still running.'
      : 'skip: do not start a new run while the previous one is still running')
    : (f.overlap === 'queue'
      ? 'queue: always open a new task, even if the previous run is still open.'
      : 'skip: skip the firing when the previous run\u2019s task is still open.');

  return (
    <Modal labelledBy="trigger-form-title" onClose={onClose} panelStyle={styles.panel}>
      <div style={styles.header}>
        <h2 id="trigger-form-title" style={styles.heading}>{heading}</h2>
        <button style={styles.closeBtn} onClick={onClose} aria-label="Close">×</button>
      </div>
      <form onSubmit={handleSubmit} style={styles.form}>
        <TriggerTargetFields f={f} target={target} slot="top" />
        <label style={R.fieldLabelStyle()}>
          Name *
          <input
            style={R.inputStyle()}
            value={f.name}
            onChange={(e) => f.setName(e.target.value)}
            placeholder={target === 'workflow' ? 'nightly-quality' : 'nightly-triage'}
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
        <TriggerTargetFields f={f} target={target} slot="mid" />
        <label style={R.fieldLabelStyle()}>
          Overlap
          <select style={R.inputStyle()} value={f.overlap} onChange={(e) => f.setOverlap(e.target.value)}>
            <option value="skip">skip</option>
            <option value="queue">queue</option>
          </select>
          <span style={styles.hint}>{overlapHint}</span>
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
            {f.pending ? 'Saving…' : f.isEdit ? 'Save changes' : HEADINGS[target].create}
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
  hint: {
    fontSize: '0.6875rem', color: T.colors.textDim,
  } as React.CSSProperties,
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
