import { useEffect, useState } from 'react';
import type { RuntimeConfig } from '../../shared/types';
import * as T from '../../shared/styles/tokens';

interface Props {
  config: RuntimeConfig;
  onSave: (updates: Partial<RuntimeConfig>) => Promise<void>;
}

export function ConfigEditor({ config, onSave }: Props) {
  const [maxConcurrent, setMaxConcurrent] = useState(String(config.max_concurrent));
  const [maxOverrides, setMaxOverrides] = useState(config.max_concurrent_overrides);
  const [model, setModel] = useState(config.model);
  const [coder, setCoder] = useState(config.coder);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setMaxConcurrent(String(config.max_concurrent));
    setMaxOverrides(config.max_concurrent_overrides);
    setModel(config.model);
    setCoder(config.coder);
  }, [config]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    // Success and failure both toast via usePutConfig; nothing to show inline.
    try {
      await onSave({
        max_concurrent: Number(maxConcurrent),
        max_concurrent_overrides: maxOverrides,
        model,
        coder,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={styles.panel}>
      <h3 style={styles.title}>Runtime Config</h3>
      <form onSubmit={handleSave} style={styles.form}>
        <div style={styles.fields}>
          <label style={styles.label}>
            Max concurrent
            <input
              type="number"
              style={styles.input}
              value={maxConcurrent}
              onChange={e => setMaxConcurrent(e.target.value)}
              min={1}
            />
          </label>
          <label style={styles.label}>
            Per-coder concurrency (e.g. claude:2,opencode:4)
            <input
              style={styles.input}
              value={maxOverrides}
              onChange={e => setMaxOverrides(e.target.value)}
              placeholder="claude:2,opencode:4"
            />
          </label>
          <label style={styles.label}>
            Default coder
            <input
              style={styles.input}
              value={coder}
              onChange={e => setCoder(e.target.value)}
            />
          </label>
          <label style={styles.label}>
            Default model
            <input
              style={styles.input}
              value={model}
              onChange={e => setModel(e.target.value)}
            />
          </label>
        </div>
        <div style={styles.footer}>
          <button type="submit" style={styles.saveBtn} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  );
}

const styles = {
  panel: {
    ...T.panel,
    padding: '1rem 1.25rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.875rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  form: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.875rem',
  } as React.CSSProperties,
  fields: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.625rem',
  } as React.CSSProperties,
  label: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.3rem',
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  input: {
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textPrimary,
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
    outline: 'none',
  } as React.CSSProperties,
  footer: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    justifyContent: 'flex-end',
  } as React.CSSProperties,
  saveBtn: {
    ...T.btnPrimary,
  } as React.CSSProperties,
};
