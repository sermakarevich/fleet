// Small controlled inputs shared by every settings section: text,
// number, boolean and select plus the restart-required badge. Rendered
// by ConfigSection; one render test lives in SettingsPage.test.tsx.
import * as T from '../../shared/styles/tokens';

interface FieldWrapProps {
  label: string;
  help: string;
  error?: string;
  restart?: boolean;
  children: React.ReactNode;
}

export function RestartBadge() {
  return (
    <span title="Changing this setting needs a serve restart" style={styles.restart}>
      restart required
    </span>
  );
}

export function FieldRow({ label, help, error, restart, children }: FieldWrapProps) {
  return (
    <label style={styles.row}>
      <span style={styles.labelLine}>
        <span style={styles.label}>{label}</span>
        {restart && <RestartBadge />}
      </span>
      {children}
      <span style={styles.help}>{help}</span>
      {error && <span style={styles.error}>{error}</span>}
    </label>
  );
}

interface TextProps {
  value: string;
  placeholder?: string;
  onChange: (v: string) => void;
}

export function SettingText({ value, placeholder, onChange }: TextProps) {
  return (
    <input
      style={styles.input}
      value={value}
      placeholder={placeholder}
      onChange={e => onChange(e.target.value)}
    />
  );
}

export function SettingNumber({ value, onChange }: TextProps) {
  return (
    <input
      type="number"
      style={styles.input}
      value={value}
      onChange={e => onChange(e.target.value)}
    />
  );
}

export function SettingBool({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <input
      type="checkbox"
      style={styles.checkbox}
      checked={checked}
      onChange={e => onChange(e.target.checked)}
    />
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

export function SettingSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: SelectOption[];
  onChange: (v: string) => void;
}) {
  // The saved value always stays selectable, even when the coders list
  // does not mention it (e.g. a removed coder).
  const withCurrent =
    value && !options.some(o => o.value === value)
      ? [...options, { value, label: `${value} (current)` }]
      : options;
  return (
    <select style={styles.input} value={value} onChange={e => onChange(e.target.value)}>
      {withCurrent.map(o => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

const styles = {
  row: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.3rem',
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  labelLine: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  } as React.CSSProperties,
  label: {
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  restart: {
    padding: '0.1rem 0.5rem',
    background: T.colors.warningBg,
    borderRadius: '10rem',
    fontSize: '0.6875rem',
    fontWeight: 600,
    color: T.colors.warningFg,
    whiteSpace: 'nowrap' as const,
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
    maxWidth: '24rem',
  } as React.CSSProperties,
  checkbox: {
    accentColor: T.colors.accent,
    cursor: 'pointer',
    width: '1rem',
    height: '1rem',
  } as React.CSSProperties,
  help: {
    color: T.colors.textMuted,
    fontSize: '0.75rem',
  } as React.CSSProperties,
  error: {
    color: T.colors.danger,
    fontSize: '0.75rem',
  } as React.CSSProperties,
};
