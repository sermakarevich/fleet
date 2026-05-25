import { useEffect, useState } from 'react';
import type { RuntimeConfig } from '../../types';

interface Props {
  config: RuntimeConfig;
  onSave: (updates: Partial<RuntimeConfig>) => Promise<void>;
}

export function ConfigEditor({ config, onSave }: Props) {
  const [maxConcurrent, setMaxConcurrent] = useState(String(config.max_concurrent));
  const [model, setModel] = useState(config.model);
  const [coder, setCoder] = useState(config.coder);
  const [threshold, setThreshold] = useState(String(config.context_pressure_threshold_pct));
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setMaxConcurrent(String(config.max_concurrent));
    setModel(config.model);
    setCoder(config.coder);
    setThreshold(String(config.context_pressure_threshold_pct));
  }, [config]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await onSave({
        max_concurrent: Number(maxConcurrent),
        model,
        coder,
        context_pressure_threshold_pct: Number(threshold),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
          <label style={styles.label}>
            Context pressure threshold (%)
            <input
              type="number"
              style={styles.input}
              value={threshold}
              onChange={e => setThreshold(e.target.value)}
              min={0}
              max={100}
            />
          </label>
        </div>
        <div style={styles.footer}>
          {saved && <span style={styles.savedMsg}>Saved</span>}
          {error && <span style={styles.errorMsg}>{error}</span>}
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
    background: '#1c1c20',
    border: '1px solid #3f3f46',
    borderRadius: 8,
    padding: '1rem 1.25rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.875rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
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
    color: '#a1a1aa',
  } as React.CSSProperties,
  input: {
    background: '#09090b',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#e4e4e7',
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
  savedMsg: {
    color: '#22c55e',
    fontSize: '0.8125rem',
    fontWeight: 500,
  } as React.CSSProperties,
  errorMsg: {
    color: '#ef4444',
    fontSize: '0.8125rem',
    flex: 1,
  } as React.CSSProperties,
  saveBtn: {
    padding: '0.4rem 0.875rem',
    background: '#3b82f6',
    border: '1px solid #3b82f6',
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.875rem',
    fontWeight: 500,
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
