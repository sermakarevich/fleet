// One settings section card: title, blurb, its fields by kind, one
// Save button with a dirty indicator and the PUT error next to the
// fields. Rendered by SettingsPage for every editable section; field
// metadata comes from settingsSections.
import { useState } from 'react';
import * as T from '../../shared/styles/tokens';
import type { CoderInfo } from '../../shared/types';
import { FieldRow, SettingBool, SettingNumber, SettingSelect, SettingText } from './fields';
import { ContextWindowsTable, OverridesTable } from './PairTables';
import {
  FIELD_DEFS,
  SECTIONS,
  fieldsFor,
  type SectionId,
  type SettingKey,
} from './settingsSections';
import type { Draft, DraftValue } from './useSettingsForm';

interface Props {
  section: SectionId;
  draft: Draft;
  setField: (key: SettingKey, value: DraftValue) => void;
  dirty: boolean;
  isFieldDirty: (key: SettingKey) => boolean;
  saving: boolean;
  error?: string;
  coders: CoderInfo[];
  restartFields: Set<string>;
  onSave: () => void;
}

export function ConfigSection({
  section,
  draft,
  setField,
  dirty,
  isFieldDirty,
  saving,
  error,
  coders,
  restartFields,
  onSave,
}: Props) {
  const meta = SECTIONS.find(s => s.id === section);
  const [tablesValid, setTablesValid] = useState<Record<string, boolean>>({});
  const coderNames = coders.map(c => c.name);
  const modelNames = [...new Set(coders.map(c => c.default_model).filter(Boolean))];
  const blocked = Object.values(tablesValid).some(v => !v);
  if (!meta) return null;

  const markTable = (key: string) => (valid: boolean) =>
    setTablesValid(prev => (prev[key] === valid ? prev : { ...prev, [key]: valid }));

  return (
    <section id={`settings-${section}`} style={styles.card} aria-label={meta.title}>
      <h3 style={styles.title}>
        {meta.title}
        {dirty && (
          <span title="Unsaved changes" style={styles.dirty}>
            ●
          </span>
        )}
      </h3>
      <p style={styles.blurb}>{meta.blurb}</p>
      <div style={styles.fields}>
        {fieldsFor(section).map(key => {
          const def = FIELD_DEFS[key];
          const raw = draft[key];
          const str = typeof raw === 'boolean' ? String(raw) : raw;
          const restart = restartFields.has(key);
          const fieldError = isFieldDirty(key) && error ? error : undefined;
          switch (def.kind) {
            case 'boolean':
              return (
                <FieldRow key={key} label={def.label} help={def.help} error={fieldError} restart={restart}>
                  <SettingBool checked={raw === true} onChange={v => setField(key, v)} />
                </FieldRow>
              );
            case 'number':
              return (
                <FieldRow key={key} label={def.label} help={def.help} error={fieldError} restart={restart}>
                  <SettingNumber value={str} onChange={v => setField(key, v)} />
                </FieldRow>
              );
            case 'coder':
              return (
                <FieldRow key={key} label={def.label} help={def.help} error={fieldError} restart={restart}>
                  <SettingSelect
                    value={str}
                    options={coderNames.map(name => ({ value: name, label: name }))}
                    onChange={v => setField(key, v)}
                  />
                </FieldRow>
              );
            case 'model':
              return (
                <FieldRow key={key} label={def.label} help={def.help} error={fieldError} restart={restart}>
                  <SettingSelect
                    value={str}
                    options={modelNames.map(name => ({ value: name, label: name }))}
                    onChange={v => setField(key, v)}
                  />
                </FieldRow>
              );
            case 'isolation':
              return (
                <FieldRow key={key} label={def.label} help={def.help} error={fieldError} restart={restart}>
                  <SettingSelect
                    value={str}
                    options={[
                      { value: 'worktree', label: 'worktree' },
                      { value: 'none', label: 'none' },
                    ]}
                    onChange={v => setField(key, v)}
                  />
                </FieldRow>
              );
            case 'stall-action':
              return (
                <FieldRow key={key} label={def.label} help={def.help} error={fieldError} restart={restart}>
                  <SettingSelect
                    value={str}
                    options={[
                      { value: 'warn', label: 'warn' },
                      { value: 'kill', label: 'kill' },
                    ]}
                    onChange={v => setField(key, v)}
                  />
                </FieldRow>
              );
            case 'overrides':
              return (
                <FieldRow key={key} label={def.label} help={def.help} error={fieldError} restart={restart}>
                  <OverridesTable
                    value={str}
                    coderNames={coderNames}
                    onChange={v => setField(key, v)}
                    onValidityChange={markTable(key)}
                  />
                </FieldRow>
              );
            case 'context-windows':
              return (
                <FieldRow key={key} label={def.label} help={def.help} error={fieldError} restart={restart}>
                  <ContextWindowsTable
                    value={str}
                    modelNames={modelNames}
                    onChange={v => setField(key, v)}
                    onValidityChange={markTable(key)}
                  />
                </FieldRow>
              );
            default:
              return (
                <FieldRow
                  key={key}
                  label={def.label}
                  help={def.help}
                  error={fieldError}
                  restart={restart}
                >
                  <SettingText
                    value={str}
                    placeholder={def.placeholder}
                    onChange={v => setField(key, v)}
                  />
                </FieldRow>
              );
          }
        })}
      </div>
      <div style={styles.footer}>
        <button
          type="button"
          style={dirty && !blocked ? styles.save : styles.saveIdle}
          disabled={!dirty || saving || blocked}
          onClick={onSave}
        >
          {saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
        </button>
      </div>
    </section>
  );
}

const styles = {
  card: {
    ...T.panel,
    padding: '1rem 1.25rem',
    scrollMarginTop: '3.5rem',
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.25rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  } as React.CSSProperties,
  dirty: {
    color: T.colors.amber,
    fontSize: '0.625rem',
  } as React.CSSProperties,
  blurb: {
    margin: '0 0 0.875rem',
    fontSize: '0.8125rem',
    color: T.colors.textMuted,
  } as React.CSSProperties,
  fields: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.875rem',
  } as React.CSSProperties,
  footer: {
    display: 'flex',
    justifyContent: 'flex-end',
    marginTop: '1rem',
  } as React.CSSProperties,
  save: {
    ...T.btnPrimary,
  } as React.CSSProperties,
  saveIdle: {
    ...T.btnGhost,
  } as React.CSSProperties,
};
