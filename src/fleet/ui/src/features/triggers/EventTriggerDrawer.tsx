// Slide-over detail view for one event trigger (ADR 0011): definition
// summary, firing history linking each task_id to the worker page, and a
// "Preview now" dry run showing the events and decisions from
// POST /api/triggers/{id}/preview. Called by EventTriggerTable when a row
// is selected (?trigger=).
import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  useDeleteTrigger,
  usePreviewTrigger,
  useSetTriggerEnabled,
  useTrigger,
} from '../../shared/hooks/useApi';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { Confirm } from '../../shared/ui/Confirm';
import { LoadingState } from '../../shared/ui/LoadingState';
import { Modal } from '../../shared/ui/Modal';
import type { EventTrigger, Firing, TriggerPreview } from './types';
import { EventTriggerForm } from './EventTriggerForm';

// Section heading inside the drawer.
function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 style={styles.sectionTitle}>{children}</h3>;
}

// One label/value line in the Definition section.
function DefRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={styles.defRow}>
      <span style={styles.defLabel}>{label}</span>
      <span style={styles.defValue}>{children}</span>
    </div>
  );
}

// Definition summary: source plus params, task template and policy.
function TriggerDefinition({ trigger }: { trigger: EventTrigger }) {
  const params = Object.entries(trigger.source_params ?? {});
  return (
    <>
      <DefRow label="source">
        <span style={R.monoStyle()}>{trigger.source}</span>
      </DefRow>
      {params.map(([key, value]) => (
        <DefRow key={key} label={key}>
          <span style={R.monoStyle()} title={value}>{value}</span>
        </DefRow>
      ))}
      <DefRow label="cwd">{trigger.cwd ?? <span style={R.dimStyle()}>—</span>}</DefRow>
      <DefRow label="coder/model">
        {trigger.coder ?? <span style={R.dimStyle()}>default</span>}
        {trigger.model ? ` / ${trigger.model}` : ''}
      </DefRow>
      <DefRow label="priority">{trigger.priority}</DefRow>
      <DefRow label="isolation">{trigger.isolation ?? <span style={R.dimStyle()}>default</span>}</DefRow>
      {(trigger.labels ?? []).length > 0 && (
        <DefRow label="labels">{(trigger.labels ?? []).join(', ')}</DefRow>
      )}
      <DefRow label="max open">{trigger.max_open}</DefRow>
      <DefRow label="cooldown">{trigger.cooldown_sec}s</DefRow>
      <SectionTitle>Title template</SectionTitle>
      <pre style={styles.pre}>{trigger.title}</pre>
      {trigger.description && <pre style={styles.pre}>{trigger.description}</pre>}
    </>
  );
}

// One firing row: sequence number, event key, time, linked task and reason.
function FiringRow({ firing }: { firing: Firing }) {
  return (
    <div style={styles.firingRow}>
      <span style={R.merge(R.monoStyle(), styles.firingN)}>#{firing.n}</span>
      <span style={R.merge(R.monoStyle(), styles.firingKey)} title={firing.event_key}>
        {firing.event_key}
      </span>
      <span style={styles.firingTs}>{fmtTs(firing.fired_at)}</span>
      {firing.task_id ? (
        <Link to={`/workers/${firing.task_id}`} style={styles.link}>
          {firing.task_id}
        </Link>
      ) : (
        <span style={R.dimStyle()}>{firing.skipped ? 'skipped' : '—'}</span>
      )}
      <span style={styles.firingReason} title={firing.reason}>{firing.reason}</span>
    </div>
  );
}

// Firing history for one trigger, newest last (append-only log order).
function FiringsList({ firings }: { firings: Firing[] }) {
  if (firings.length === 0) {
    return <p style={R.dimStyle()}>No firings yet.</p>;
  }
  return (
    <>
      {firings.map((firing) => (
        <FiringRow key={`${firing.trigger_id}-${firing.n}`} firing={firing} />
      ))}
    </>
  );
}

// Dry-run result: one event payload plus its decision string per row.
function PreviewResult({ preview }: { preview: TriggerPreview }) {
  if (preview.events.length === 0) {
    return <p style={R.dimStyle()}>No events right now — nothing would fire.</p>;
  }
  return (
    <>
      {preview.events.map((event, i) => (
        <div key={i} style={styles.previewRow}>
          <pre style={styles.pre}>{JSON.stringify(event, null, 2)}</pre>
          <span style={styles.decision}>→ {preview.decisions[i] ?? '?'}</span>
        </div>
      ))}
    </>
  );
}

// Preview section: button plus the last dry-run result or its error.
function PreviewSection({ triggerId }: { triggerId: string }) {
  const preview = usePreviewTrigger();
  const [result, setResult] = useState<TriggerPreview | null>(null);

  function handlePreview() {
    setResult(null);
    void preview.mutateAsync(triggerId).then(setResult, () => undefined);
  }

  return (
    <section style={styles.section}>
      <SectionTitle>Preview</SectionTitle>
      <button
        style={styles.previewBtn}
        disabled={preview.isPending}
        onClick={handlePreview}
      >
        {preview.isPending ? 'Previewing…' : 'Preview now'}
      </button>
      {preview.error && (
        <p style={R.errorMsgStyle()}>Preview failed: {String(preview.error)}</p>
      )}
      {result && <PreviewResult preview={result} />}
    </section>
  );
}

// Row of action buttons under the title: enable, edit, delete.
function DrawerActions({
  triggerId, enabled, onEdit, onDeleted,
}: {
  triggerId: string; enabled: boolean; onEdit: () => void; onDeleted: () => void;
}) {
  const setEnabled = useSetTriggerEnabled();
  const deleteTrigger = useDeleteTrigger();
  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleDelete() {
    void deleteTrigger.mutateAsync(triggerId).then(onDeleted);
  }

  return (
    <div style={styles.actionsRow}>
      <button
        style={styles.ghostBtn}
        disabled={setEnabled.isPending}
        onClick={() => setEnabled.mutate({ id: triggerId, enabled: !enabled })}
      >
        {enabled ? 'Disable' : 'Enable'}
      </button>
      <button style={styles.ghostBtn} onClick={onEdit}>
        Edit
      </button>
      {confirmDelete ? (
        <Confirm
          verb="Delete"
          onConfirm={handleDelete}
          onCancel={() => setConfirmDelete(false)}
        />
      ) : (
        <button
          style={styles.deleteBtn}
          disabled={deleteTrigger.isPending}
          onClick={() => setConfirmDelete(true)}
        >
          Delete
        </button>
      )}
    </div>
  );
}

// Drawer shell: header, actions, definition, firings, preview, edit form.
export function EventTriggerDrawer({
  triggerId, onClose,
}: {
  triggerId: string; onClose: () => void;
}) {
  const { data: detail, isLoading, error } = useTrigger(triggerId);
  const [showEdit, setShowEdit] = useState(false);

  const trigger = detail?.trigger ?? null;
  const firings = detail?.firings ?? [];

  return (
    <Modal labelledBy="event-trigger-drawer-title" onClose={onClose} placement="right" panelStyle={R.drawerStyle()}>
      <div style={styles.header}>
        <span id="event-trigger-drawer-title" style={styles.id}>{triggerId}</span>
        <button style={styles.closeBtn} onClick={onClose} title="Close" aria-label="Close">✕</button>
      </div>
      <div style={styles.body}>
        {isLoading && <LoadingState />}
        {error && <p style={R.errorMsgStyle()}>Error: {String(error)}</p>}
        {trigger && (
          <>
            <DrawerActions
              triggerId={triggerId}
              enabled={trigger.enabled}
              onEdit={() => setShowEdit(true)}
              onDeleted={onClose}
            />
            <h2 style={styles.title}>{trigger.name}</h2>
            <div style={styles.metaRow}>
              <span style={trigger.enabled ? styles.enabledOn : styles.enabledOff}>
                {trigger.enabled ? 'enabled' : 'disabled'}
              </span>
            </div>
            <section style={styles.section}>
              <SectionTitle>Definition</SectionTitle>
              <TriggerDefinition trigger={trigger} />
            </section>
            <section style={styles.section}>
              <SectionTitle>Firings ({firings.length})</SectionTitle>
              <FiringsList firings={firings} />
            </section>
            <PreviewSection triggerId={triggerId} />
          </>
        )}
      </div>
      {showEdit && trigger && (
        <EventTriggerForm
          initial={trigger}
          onClose={() => setShowEdit(false)}
          onSaved={() => undefined}
        />
      )}
    </Modal>
  );
}

const styles = {
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '0.625rem 1rem', borderBottom: `1px solid ${T.colors.borderSubtle}`, flexShrink: 0,
  } as React.CSSProperties,
  id: {
    fontFamily: 'monospace', color: T.colors.link, fontSize: '0.875rem', fontWeight: 600,
  } as React.CSSProperties,
  closeBtn: {
    background: 'transparent', border: 'none', color: T.colors.textSecondary,
    cursor: 'pointer', fontSize: '1rem', lineHeight: 1, padding: '0.25rem',
  } as React.CSSProperties,
  body: {
    padding: '1rem', overflowY: 'auto' as const, flex: 1,
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.75rem', fontSize: '1rem', fontWeight: 600, color: T.colors.textBright, lineHeight: 1.4,
  } as React.CSSProperties,
  metaRow: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
    flexWrap: 'wrap' as const, marginBottom: '0.875rem',
  } as React.CSSProperties,
  enabledOn: {
    ...T.badge, background: T.colors.greenDark, color: T.colors.mintPale,
  } as React.CSSProperties,
  enabledOff: {
    ...T.badge, background: T.colors.borderSubtle, color: T.colors.textSecondary,
  } as React.CSSProperties,
  section: { marginBottom: '1.25rem' } as React.CSSProperties,
  sectionTitle: {
    margin: '0 0 0.5rem', fontSize: '0.75rem', fontWeight: 600, color: T.colors.textDim,
    textTransform: 'uppercase' as const, letterSpacing: '0.05em',
  } as React.CSSProperties,
  defRow: {
    display: 'flex', gap: '0.5rem', padding: '0.25rem 0',
    fontSize: '0.8125rem', color: T.colors.textBody,
  } as React.CSSProperties,
  defLabel: {
    width: '6.5rem', flexShrink: 0, color: T.colors.textDim,
  } as React.CSSProperties,
  defValue: {
    flex: 1, minWidth: 0, overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  pre: {
    margin: '0 0 0.5rem', padding: '0.625rem 0.75rem', background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`, borderRadius: '0.375rem', color: T.colors.textBody,
    fontSize: '0.8125rem', fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const, lineHeight: 1.5,
  } as React.CSSProperties,
  firingRow: {
    display: 'flex', alignItems: 'baseline', gap: '0.5rem', padding: '0.25rem 0',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  firingN: { flexShrink: 0 } as React.CSSProperties,
  firingKey: {
    flex: 1, minWidth: 0, overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  firingTs: { flexShrink: 0 } as React.CSSProperties,
  firingReason: {
    flexShrink: 0, maxWidth: '10rem', overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  link: { color: T.colors.link, textDecoration: 'none' } as React.CSSProperties,
  previewRow: { marginTop: '0.5rem' } as React.CSSProperties,
  decision: {
    display: 'block', fontSize: '0.8125rem', color: T.colors.textSecondary,
    fontFamily: 'ui-monospace, monospace', marginBottom: '0.5rem',
  } as React.CSSProperties,
  previewBtn: {
    ...T.btnPrimary, padding: '0.3rem 0.75rem', fontSize: '0.8125rem',
  } as React.CSSProperties,
  actionsRow: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
    flexWrap: 'wrap' as const, marginBottom: '1.25rem',
  } as React.CSSProperties,
  ghostBtn: {
    ...T.btnGhost, padding: '0.3rem 0.75rem', fontSize: '0.8125rem',
  } as React.CSSProperties,
  deleteBtn: {
    ...T.btnDanger, padding: '0.3rem 0.75rem', fontSize: '0.8125rem',
  } as React.CSSProperties,
};
