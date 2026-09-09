// Table editors for the two "pairs" settings: per-coder concurrency
// overrides and per-model context windows. Both edit a comma-separated
// "key:value" string and only propagate valid states upward. Rendered by
// ConfigSection for the overrides / context-windows field kinds.
import { useEffect, useState } from 'react';
import * as T from '../../shared/styles/tokens';
import { SettingSelect } from './fields';

interface PairRow {
  key: string;
  val: string;
}

function parsePairs(raw: string): PairRow[] {
  if (!raw.trim()) return [];
  return raw
    .split(',')
    .map(part => part.trim())
    .filter(Boolean)
    .map(part => {
      const idx = part.indexOf(':');
      if (idx < 0) return { key: part, val: '' };
      return { key: part.slice(0, idx).trim(), val: part.slice(idx + 1).trim() };
    });
}

function usePairState(
  value: string,
  onChange: (v: string) => void,
  onValidityChange: (valid: boolean) => void,
) {
  const [rows, setRows] = useState<PairRow[]>(() => parsePairs(value));

  useEffect(() => {
    setRows(parsePairs(value));
  }, [value]);

  const complete = rows.filter(r => r.key.trim() !== '');
  const invalid = complete.some(r => !/^\d+$/.test(r.val.trim()) || Number(r.val) <= 0);
  const blankKey = rows.some(r => r.key.trim() === '' && r.val.trim() !== '');
  const valid = !invalid && !blankKey;

  useEffect(() => {
    onValidityChange(valid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valid]);

  const commit = (next: PairRow[]) => {
    setRows(next);
    const done = next.filter(r => r.key.trim() !== '');
    const bad = done.some(r => !/^\d+$/.test(r.val.trim()) || Number(r.val) <= 0);
    const blank = next.some(r => r.key.trim() === '' && r.val.trim() !== '');
    if (!bad && !blank) {
      onChange(done.map(r => `${r.key.trim()}:${r.val.trim()}`).join(','));
    }
  };

  return { rows, valid, commit };
}

interface TableProps {
  value: string;
  onChange: (v: string) => void;
  onValidityChange: (valid: boolean) => void;
}

export function OverridesTable({ value, onChange, onValidityChange, coderNames }: TableProps & { coderNames: string[] }) {
  const { rows, valid, commit } = usePairState(value, onChange, onValidityChange);
  const options = coderNames.map(name => ({ value: name, label: name }));

  return (
    <div style={styles.wrap}>
      {rows.length === 0 && <div style={styles.empty}>No per-coder limits — every coder uses max concurrent.</div>}
      {rows.map((row, i) => (
        <div key={i} style={styles.tr}>
          <SettingSelect
            value={row.key}
            options={options}
            onChange={v => commit(rows.map((r, j) => (j === i ? { ...r, key: v } : r)))}
          />
          <input
            type="number"
            aria-label="limit"
            style={styles.num}
            value={row.val}
            min={1}
            onChange={e => commit(rows.map((r, j) => (j === i ? { ...r, val: e.target.value } : r)))}
          />
          <button
            type="button"
            style={styles.remove}
            onClick={() => commit(rows.filter((_, j) => j !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      {!valid && <div style={styles.error}>Each row needs a coder and a limit of at least 1.</div>}
      <button type="button" style={styles.add} onClick={() => commit([...rows, { key: '', val: '' }])}>
        + Add coder limit
      </button>
    </div>
  );
}

export function ContextWindowsTable({ value, onChange, onValidityChange, modelNames }: TableProps & { modelNames: string[] }) {
  const { rows, valid, commit } = usePairState(value, onChange, onValidityChange);

  return (
    <div style={styles.wrap}>
      {rows.length === 0 && <div style={styles.empty}>No per-model windows — coders use their built-ins.</div>}
      {rows.map((row, i) => (
        <div key={i} style={styles.tr}>
          <input
            aria-label="model"
            style={styles.input}
            value={row.key}
            list="settings-model-names"
            placeholder="model"
            onChange={e => commit(rows.map((r, j) => (j === i ? { ...r, key: e.target.value } : r)))}
          />
          <input
            type="number"
            aria-label="tokens"
            style={styles.num}
            value={row.val}
            min={1}
            onChange={e => commit(rows.map((r, j) => (j === i ? { ...r, val: e.target.value } : r)))}
          />
          <button
            type="button"
            style={styles.remove}
            onClick={() => commit(rows.filter((_, j) => j !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <datalist id="settings-model-names">
        {modelNames.map(name => (
          <option key={name} value={name} />
        ))}
      </datalist>
      {!valid && <div style={styles.error}>Each row needs a model and a token count of at least 1.</div>}
      <button type="button" style={styles.add} onClick={() => commit([...rows, { key: '', val: '' }])}>
        + Add model window
      </button>
    </div>
  );
}

const styles = {
  wrap: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.375rem',
    maxWidth: '24rem',
  } as React.CSSProperties,
  empty: {
    color: T.colors.textMuted,
    fontSize: '0.75rem',
  } as React.CSSProperties,
  tr: {
    display: 'flex',
    gap: '0.375rem',
    alignItems: 'center',
  } as React.CSSProperties,
  input: {
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textPrimary,
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
    outline: 'none',
    flex: 1,
    minWidth: 0,
  } as React.CSSProperties,
  num: {
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textPrimary,
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
    outline: 'none',
    width: '7rem',
    flexShrink: 0,
  } as React.CSSProperties,
  add: {
    alignSelf: 'flex-start',
    background: 'transparent',
    border: `1px dashed ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.8125rem',
    padding: '0.3rem 0.6rem',
  } as React.CSSProperties,
  remove: {
    background: 'transparent',
    border: 'none',
    color: T.colors.textMuted,
    cursor: 'pointer',
    fontSize: '0.8125rem',
    flexShrink: 0,
  } as React.CSSProperties,
  error: {
    color: T.colors.danger,
    fontSize: '0.75rem',
  } as React.CSSProperties,
};
