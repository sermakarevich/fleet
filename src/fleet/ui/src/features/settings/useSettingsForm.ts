// Whole-page form state for the settings page (ADR 0009). One draft
// for every RuntimeConfig field, one dirty set, one Save per section.
// Rendered only by SettingsPage; per-section rendering lives in
// ConfigSection.
import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '../../shared/api';
import { usePutConfig } from '../../shared/hooks/useApi';
import type { RuntimeConfig } from '../../shared/types';
import { FIELD_DEFS, fieldsFor, type SectionId, type SettingKey } from './settingsSections';

export type DraftValue = string | boolean;
export type Draft = Record<SettingKey, DraftValue>;

function toDraft(config: RuntimeConfig): Draft {
  const draft = {} as Draft;
  for (const key of Object.keys(FIELD_DEFS) as SettingKey[]) {
    const value = config[key];
    if (typeof value === 'boolean') draft[key] = value;
    else if (Array.isArray(value)) draft[key] = value.join(', ');
    else draft[key] = String(value ?? '');
  }
  return draft;
}

function parseList(raw: string): string[] {
  return raw
    .split(',')
    .map(part => part.trim())
    .filter(Boolean);
}

function sameValue(draft: DraftValue, saved: DraftValue): boolean {
  if (typeof saved === 'boolean') return draft === saved;
  if (typeof draft === 'boolean') return false;
  const savedList = parseList(String(saved));
  const draftList = parseList(draft);
  // Plain scalars compare as strings; comma lists compare element-wise so
  // "a, b" matches a saved ["a", "b"].
  if (!String(saved).includes(',') && savedList.length <= 1 && draftList.length <= 1) {
    return draft.trim() === String(saved).trim();
  }
  return draftList.length === savedList.length && draftList.every((v, i) => v === savedList[i]);
}

export function useSettingsForm(config: RuntimeConfig | undefined) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState<Set<SettingKey>>(new Set());
  const [sectionErrors, setSectionErrors] = useState<Partial<Record<SectionId, string>>>({});
  const putConfig = usePutConfig();
  const savedRef = useRef<Draft | null>(null);
  if (config) savedRef.current = toDraft(config);

  // Fresh server data flows into clean fields; dirty edits survive refetch.
  useEffect(() => {
    if (!config) return;
    const fresh = toDraft(config);
    setDraft(prev => {
      if (!prev) return fresh;
      const merged = { ...fresh };
      dirty.forEach(key => {
        merged[key] = prev[key];
      });
      return merged;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  const setField = useCallback((key: SettingKey, value: DraftValue) => {
    setDraft(prev => (prev ? { ...prev, [key]: value } : prev));
    setDirty(prev => {
      const next = new Set(prev);
      const saved = savedRef.current?.[key];
      if (saved !== undefined && sameValue(value, saved)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const isDirty = useCallback(
    (section: SectionId) => fieldsFor(section).some(key => dirty.has(key)),
    [dirty],
  );

  const isFieldDirty = useCallback((key: SettingKey) => dirty.has(key), [dirty]);

  // Changed fields of one section (PUT accepts partial updates).
  const sectionChanges = useCallback(
    (section: SectionId): Partial<RuntimeConfig> => {
      const changes: Record<string, DraftValue> = {};
      if (!draft) return changes;
      for (const key of fieldsFor(section)) {
        if (dirty.has(key)) changes[key] = draft[key];
      }
      return changes as Partial<RuntimeConfig>;
    },
    [draft, dirty],
  );

  const saveSection = useCallback(
    async (section: SectionId): Promise<boolean> => {
      const changes = sectionChanges(section);
      if (Object.keys(changes).length === 0) return true;
      try {
        // The backend merges partial updates; restart_required is a GET-only
        // meta key and is never sent back (PUT would 422 on it).
        await putConfig.mutateAsync(changes);
      } catch (err) {
        setSectionErrors(prev => ({ ...prev, [section]: errorMessage(err) }));
        return false;
      }
      setDirty(prev => {
        const next = new Set(prev);
        fieldsFor(section).forEach(key => next.delete(key));
        return next;
      });
      setSectionErrors(prev => ({ ...prev, [section]: undefined }));
      return true;
    },
    [sectionChanges, putConfig],
  );

  return {
    draft,
    setField,
    isDirty,
    isFieldDirty,
    sectionChanges,
    saveSection,
    saving: putConfig.isPending,
    sectionErrors,
  };
}
