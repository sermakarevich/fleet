/**
 * Modal form for scheduling a workflow on a cron.
 * Thin shell over useRecurringForm: workflow picker, name, cron input with
 * the shared presets and live preview, timezone, overlap and actions.
 * Called by RecurringPage (create) and RecurringDrawer (edit).
 */
import * as R from '../../shared/styles/recipes';
import * as T from '../../shared/styles/tokens';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import { Modal } from '../../shared/ui/Modal';
import { CRON_PRESETS } from '../schedules/cronPresets';
import { useRecurringForm, workflowOptionLabel } from './useRecurringForm';
import type { Schedule } from '../../shared/types';

interface Props {
  initial?: Schedule | null;
  onClose: () => void;
  onSaved: (schedule: Schedule) => void;
}

// Recurring-workflow create/edit modal; all state lives in useRecurringForm.
export function RecurringForm({ initial, onClose, onSaved }: Props) {
  const f = useRecurringForm({ initial, onSaved, onClose });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    void f.submit();
  }

  const previewTimes = f.preview.data?.upcoming ?? [];
  const previewError =
    f.preview.data && !f.preview.data.valid
      ? (f.preview.data.error ?? 'Invalid cron expression')
      : null;

  return (
    <Modal labelledBy="recurring-form-title" onClose={onClose} panelStyle={styles.panel}>
      <div style={styles.header}>
        <h2 id="recurring-form-title" style={styles.heading}>
          {f.isEdit ? 'Edit recurring workflow' : 'Schedule a workflow'}
        </h2>
        <button style={styles.closeBtn} onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <form onSubmit={handleSubmit} style={styles.form}>
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
        <label style={R.fieldLabelStyle()}>
          Name *
          <input
            style={R.inputStyle()}
            value={f.name}
            onChange={(e) => f.setName(e.target.value)}
            placeholder="nightly-quality"
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
            onChange={(e) => {
              if (e.target.value) f.applyPreset(e.target.value);
            }}
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
          Overlap
          <select
            style={R.inputStyle()}
            value={f.overlap}
            onChange={(e) => f.setOverlap(e.target.value)}
          >
            <option value="skip">skip</option>
            <option value="queue">queue</option>
          </select>
          <span style={styles.hint}>
            {f.overlap === 'queue'
              ? 'queue: always start a new run, even if the previous one is still running.'
              : 'skip: do not start a new run while the previous one is still running'}
          </span>
        </label>
        <label style={styles.checkRow}>
          <input
            type="checkbox"
            checked={f.enabled}
            onChange={(e) => f.setEnabled(e.target.checked)}
          />
          Enabled
        </label>
        <div style={styles.actions}>
          {f.error && <span style={styles.errorMsg}>{(f.error as Error).message}</span>}
          <button type="button" style={styles.cancelBtn} onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            style={R.merge(T.btnPrimary, R.when(!f.canSubmit, styles.submitDisabled))}
            disabled={!f.canSubmit}
          >
            {f.pending ? 'Saving…' : f.isEdit ? 'Save changes' : 'Schedule workflow'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const styles = {
  panel: {
    ...T.panel,
    width: '100%',
    maxWidth: '36rem',
    maxHeight: 'calc(100vh - 8rem)',
    overflowY: 'auto',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '1rem 1.25rem 0.75rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  heading: {
    margin: 0,
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  closeBtn: {
    background: 'none',
    border: 'none',
    color: T.colors.textDim,
    cursor: 'pointer',
    fontSize: '1.25rem',
    lineHeight: 1,
    padding: '0 0.25rem',
  } as React.CSSProperties,
  form: {
    padding: '1rem 1.25rem',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.875rem',
  } as React.CSSProperties,
  hint: {
    fontSize: '0.6875rem',
    color: T.colors.textDim,
  } as React.CSSProperties,
  checkRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    fontSize: '0.875rem',
    color: T.colors.textSecondary,
    cursor: 'pointer',
  } as React.CSSProperties,
  actions: {
    display: 'flex',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: '0.75rem',
    paddingTop: '0.5rem',
    borderTop: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  errorMsg: {
    color: T.colors.danger,
    fontSize: '0.75rem',
    flex: 1,
  } as React.CSSProperties,
  cancelBtn: {
    ...T.btnGhost,
    padding: '0.4rem 0.875rem',
    fontSize: '0.875rem',
  } as React.CSSProperties,
  previewError: {
    margin: 0,
    fontSize: '0.8125rem',
    color: T.colors.danger,
  } as React.CSSProperties,
  submitDisabled: {
    opacity: 0.45,
    cursor: 'default',
  } as React.CSSProperties,
};
