/**
 * Form state for the schedule create/edit modal.
 * Owns field values, cron preview validity, coder lookup and
 * create/update submit. Called by ScheduleForm; mirrors useNewTaskForm.
 */
import { useState } from 'react';
import { useCoders, useCreateSchedule, useCronPreview, useUpdateSchedule } from '../../shared/hooks/useApi';
import type { CoderInfo, Schedule, ScheduleInput } from '../../shared/types';

// Browser time zone, falling back to UTC when unavailable.
function defaultTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC';
  } catch {
    return 'UTC';
  }
}

interface Options {
  /** Pre-fill source for edit mode; null/undefined means create mode. */
  initial?: Schedule | null;
  /** Run after a successful save (page navigates, drawer refreshes). */
  onSaved: (schedule: Schedule) => void;
  /** Close the modal. */
  onClose: () => void;
}

// All schedule-form state plus validation and submit.
export function useScheduleForm({ initial, onSaved, onClose }: Options) {
  const [name, setName] = useState(initial?.name ?? '');
  const [cron, setCron] = useState(initial?.cron ?? '');
  const [timezone, setTimezone] = useState(initial?.timezone ?? defaultTimezone());
  const [title, setTitle] = useState(initial?.title ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [cwd, setCwd] = useState(initial?.cwd ?? '');
  const [coder, setCoder] = useState(initial?.coder ?? '');
  const [model, setModel] = useState(initial?.model ?? '');
  const [priority, setPriority] = useState(initial?.priority ?? 0);
  const [overlap, setOverlap] = useState(initial?.overlap ?? 'skip');
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);

  const { data: codersData } = useCoders();
  const preview = useCronPreview(cron, timezone);
  const createSchedule = useCreateSchedule();
  const updateSchedule = useUpdateSchedule();

  const coders: CoderInfo[] = codersData?.coders ?? [];
  const cronValid = preview.data?.valid === true;
  const pending = createSchedule.isPending || updateSchedule.isPending;
  const error = createSchedule.error ?? updateSchedule.error ?? null;
  const canSubmit = name.trim().length > 0 && title.trim().length > 0 && cronValid && !pending;

  function handleCoderChange(next: string) {
    setCoder(next);
    const info = coders.find((c) => c.name === next);
    if (info?.default_model) setModel(info.default_model);
    else if (!next) setModel('');
  }

  function applyPreset(expression: string) {
    setCron(expression);
  }

  async function submit() {
    if (!canSubmit) return;
    const payload: ScheduleInput = {
      name: name.trim(),
      cron: cron.trim(),
      timezone: timezone.trim() || undefined,
      enabled,
      title: title.trim(),
      description: description || undefined,
      cwd: cwd || undefined,
      coder: coder || undefined,
      model: model || undefined,
      priority,
      overlap,
    };
    try {
      const saved = initial
        ? await updateSchedule.mutateAsync({ id: initial.id, payload })
        : await createSchedule.mutateAsync(payload);
      onSaved(saved);
      onClose();
    } catch {
      // error surfaces via the mutation's error state in the form
    }
  }

  return {
    name, setName, cron, setCron, timezone, setTimezone,
    title, setTitle, description, setDescription, cwd, setCwd,
    coder, model, setModel, priority, setPriority,
    overlap, setOverlap, enabled, setEnabled,
    coders, preview, cronValid, canSubmit, pending, error,
    isEdit: !!initial,
    submit, handleCoderChange, applyPreset,
  };
}

export type ScheduleFormState = ReturnType<typeof useScheduleForm>;
