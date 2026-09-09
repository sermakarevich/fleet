// Modal form for creating or editing an event trigger (ADR 0011): which
// source (plus its params) and which task template to open, with the
// max_open/cooldown_sec policy. Called by EventTriggerTable (create) and
// EventTriggerDrawer (edit).
import { useState } from 'react';
import {
  useCoders,
  useCreateTrigger,
  useTriggerSources,
  useUpdateTrigger,
} from '../../shared/hooks/useApi';
import * as R from '../../shared/styles/recipes';
import * as T from '../../shared/styles/tokens';
import { Modal } from '../../shared/ui/Modal';
import type { CoderInfo, EventTrigger, TriggerInput } from '../../shared/types';

// Raw field values the payload builder reads (form state).
export interface EventTriggerPayloadFields {
  name: string;
  source: string;
  sourceParams: Record<string, string>;
  enabled: boolean;
  title: string;
  description: string;
  cwd: string;
  coder: string;
  model: string;
  priority: number;
  isolation: string;
  labels: string;
  maxOpen: number;
  cooldownSec: number;
}

// The one place that shapes an event-trigger request: blank optionals are
// omitted (the backend rejects empty coder strings), blank source params
// are dropped, and the labels box splits on commas.
export function buildEventTriggerPayload(f: EventTriggerPayloadFields): TriggerInput {
  const sourceParams: Record<string, string> = {};
  for (const [key, value] of Object.entries(f.sourceParams)) {
    if (value !== '') sourceParams[key] = value;
  }
  const labels = f.labels.split(',').map((s) => s.trim()).filter((s) => s.length > 0);
  return {
    name: f.name.trim(),
    source: f.source,
    ...(Object.keys(sourceParams).length > 0 ? { source_params: sourceParams } : {}),
    enabled: f.enabled,
    title: f.title.trim(),
    ...(f.description ? { description: f.description } : {}),
    ...(f.cwd ? { cwd: f.cwd } : {}),
    ...(f.coder ? { coder: f.coder } : {}),
    ...(f.model ? { model: f.model } : {}),
    priority: f.priority,
    ...(f.isolation ? { isolation: f.isolation } : {}),
    ...(labels.length > 0 ? { labels } : {}),
    max_open: f.maxOpen,
    cooldown_sec: f.cooldownSec,
  };
}

interface Props {
  initial?: EventTrigger | null;
  onClose: () => void;
  onSaved: (trigger: EventTrigger) => void;
}

// Event-trigger create/edit modal; all state lives in this component.
export function EventTriggerForm({ initial, onClose, onSaved }: Props) {
  const [name, setName] = useState(initial?.name ?? '');
  const [source, setSource] = useState(initial?.source ?? '');
  const [sourceParams, setSourceParams] = useState<Record<string, string>>(() => ({
    ...(initial?.source_params ?? {}),
  }));
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [title, setTitle] = useState(initial?.title ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [cwd, setCwd] = useState(initial?.cwd ?? '');
  const [coder, setCoder] = useState(initial?.coder ?? '');
  const [model, setModel] = useState(initial?.model ?? '');
  const [priority, setPriority] = useState(initial?.priority ?? 2);
  const [isolation, setIsolation] = useState(initial?.isolation ?? '');
  const [labels, setLabels] = useState((initial?.labels ?? []).join(', '));
  const [maxOpen, setMaxOpen] = useState(initial?.max_open ?? 2);
  const [cooldownSec, setCooldownSec] = useState(initial?.cooldown_sec ?? 0);

  const { data: sourcesData } = useTriggerSources();
  const { data: codersData } = useCoders();
  const createTrigger = useCreateTrigger();
  const updateTrigger = useUpdateTrigger();

  const sources = sourcesData ?? [];
  const coders: CoderInfo[] = codersData?.coders ?? [];
  // Help text per param of the picked source (rendered as param inputs).
  const paramHelp: Record<string, string> =
    sources.find((s) => s.kind === source)?.params ?? {};
  const pending = createTrigger.isPending || updateTrigger.isPending;
  const error = createTrigger.error ?? updateTrigger.error ?? null;
  const canSubmit =
    name.trim().length > 0 && source.length > 0 && title.trim().length > 0 && !pending;

  function setParam(key: string, value: string) {
    setSourceParams((prev) => ({ ...prev, [key]: value }));
  }

  function handleCoderChange(next: string) {
    setCoder(next);
    const info = coders.find((c) => c.name === next);
    if (info?.default_model) setModel(info.default_model);
    else if (!next) setModel('');
  }

  async function submit() {
    if (!canSubmit) return;
    const payload = buildEventTriggerPayload({
      name, source, sourceParams, enabled, title, description,
      cwd, coder, model, priority, isolation, labels,
      maxOpen, cooldownSec,
    });
    try {
      const saved = initial
        ? await updateTrigger.mutateAsync({ id: initial.id, payload })
        : await createTrigger.mutateAsync(payload);
      onSaved(saved);
      onClose();
    } catch {
      // error surfaces via the mutation's error state in the form
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    void submit();
  }

  const heading = initial ? 'Edit trigger' : 'New trigger';

  return (
    <Modal labelledBy="event-trigger-form-title" onClose={onClose} panelStyle={styles.panel}>
      <div style={styles.header}>
        <h2 id="event-trigger-form-title" style={styles.heading}>{heading}</h2>
        <button style={styles.closeBtn} onClick={onClose} aria-label="Close">×</button>
      </div>
      <form onSubmit={handleSubmit} style={styles.form}>
        <label style={R.fieldLabelStyle()}>
          Name *
          <input
            style={R.inputStyle()}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="blocked-investigator"
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Source *
          <select
            style={R.inputStyle()}
            value={source}
            onChange={(e) => setSource(e.target.value)}
            aria-label="Source"
          >
            <option value="">— pick a source —</option>
            {sources.map((s) => (
              <option key={s.kind} value={s.kind}>{s.kind}</option>
            ))}
          </select>
        </label>
        {Object.entries(paramHelp).map(([param, help]) => (
          <label key={param} style={R.fieldLabelStyle()}>
            {param}
            <input
              style={R.merge(R.inputStyle(), R.monoStyle())}
              value={sourceParams[param] ?? ''}
              onChange={(e) => setParam(param, e.target.value)}
              placeholder={help}
              title={help}
              aria-label={`Source param ${param}`}
              spellCheck={false}
            />
            <span style={styles.hint}>{help}</span>
          </label>
        ))}
        <label style={R.fieldLabelStyle()}>
          Title *
          <input
            style={R.inputStyle()}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Investigate {{event.task_id}} (supports {{event.*}}, {{trigger.name}}, {{n}})"
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Description
          <textarea
            style={R.inputStyle()}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Cwd
          <input
            style={R.inputStyle()}
            value={cwd}
            onChange={(e) => setCwd(e.target.value)}
            placeholder="/path/to/repo"
            spellCheck={false}
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Coder
          <select
            style={R.inputStyle()}
            value={coder}
            onChange={(e) => handleCoderChange(e.target.value)}
            aria-label="Coder"
          >
            <option value="">— default —</option>
            {coders.map((c) => (
              <option key={c.name} value={c.name}>{c.name}</option>
            ))}
          </select>
        </label>
        <label style={R.fieldLabelStyle()}>
          Model
          <input
            style={R.inputStyle()}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="sonnet"
            spellCheck={false}
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Priority
          <input
            style={R.inputStyle()}
            type="number"
            min={0}
            max={4}
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
            aria-label="Priority"
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Isolation
          <select
            style={R.inputStyle()}
            value={isolation}
            onChange={(e) => setIsolation(e.target.value)}
            aria-label="Isolation"
          >
            <option value="">— default —</option>
            <option value="worktree">worktree</option>
            <option value="none">none</option>
          </select>
        </label>
        <label style={R.fieldLabelStyle()}>
          Labels
          <input
            style={R.inputStyle()}
            value={labels}
            onChange={(e) => setLabels(e.target.value)}
            placeholder="triage, auto (comma-separated)"
            spellCheck={false}
          />
        </label>
        <label style={R.fieldLabelStyle()}>
          Max open
          <input
            style={R.inputStyle()}
            type="number"
            min={0}
            value={maxOpen}
            onChange={(e) => setMaxOpen(Number(e.target.value))}
            aria-label="Max open"
          />
          <span style={styles.hint}>How many not-yet-closed tasks this trigger may have open.</span>
        </label>
        <label style={R.fieldLabelStyle()}>
          Cooldown (sec)
          <input
            style={R.inputStyle()}
            type="number"
            min={0}
            value={cooldownSec}
            onChange={(e) => setCooldownSec(Number(e.target.value))}
            aria-label="Cooldown sec"
          />
          <span style={styles.hint}>Minimum gap between two firings of this trigger.</span>
        </label>
        <label style={styles.checkRow}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Enabled
        </label>
        <div style={styles.actions}>
          {error && <span style={styles.errorMsg}>{(error as Error).message}</span>}
          <button type="button" style={styles.cancelBtn} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" style={R.merge(T.btnPrimary, R.when(!canSubmit, styles.submitDisabled))} disabled={!canSubmit}>
            {pending ? 'Saving…' : initial ? 'Save changes' : 'New trigger'}
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
  submitDisabled: {
    opacity: 0.45, cursor: 'default',
  } as React.CSSProperties,
};
