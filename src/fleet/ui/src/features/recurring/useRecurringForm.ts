/**
 * Form state for the recurring-workflow create/edit modal.
 * Owns field values, cron preview validity, workflow lookup and
 * create/update submit. Called by RecurringForm; mirrors useScheduleForm
 * but posts target "workflow" with a workflow_id and no title/description.
 */
import { useState } from 'react';
import {
  useCronPreview,
  useCreateSchedule,
  useUpdateSchedule,
  useWorkflows,
} from '../../shared/hooks/useApi';
import type { Schedule, ScheduleInput, Workflow } from '../../shared/types';

interface Options {
  /** Pre-fill source for edit mode; null/undefined means create mode. */
  initial?: Schedule | null;
  /** Run after a successful save (page navigates, drawer refreshes). */
  onSaved: (schedule: Schedule) => void;
  /** Close the modal. */
  onClose: () => void;
}

// Browser time zone, falling back to UTC when unavailable.
function defaultTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC';
  } catch {
    return 'UTC';
  }
}

// Label for the workflow picker: name plus its stage count.
export function workflowOptionLabel(workflow: Workflow): string {
  return `${workflow.name} · ${workflow.stage_count} stage${workflow.stage_count === 1 ? '' : 's'}`;
}

// All recurring-form state plus validation and submit.
export function useRecurringForm({ initial, onSaved, onClose }: Options) {
  const [workflowId, setWorkflowId] = useState(initial?.workflow_id ?? '');
  const [name, setName] = useState(initial?.name ?? '');
  const [cron, setCron] = useState(initial?.cron ?? '');
  const [timezone, setTimezone] = useState(initial?.timezone ?? defaultTimezone());
  const [overlap, setOverlap] = useState(initial?.overlap ?? 'skip');
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);

  const { data: workflowsData } = useWorkflows();
  const preview = useCronPreview(cron, timezone);
  const createSchedule = useCreateSchedule();
  const updateSchedule = useUpdateSchedule();

  const workflows: Workflow[] = workflowsData ?? [];
  const cronValid = preview.data?.valid === true;
  const pending = createSchedule.isPending || updateSchedule.isPending;
  const error = createSchedule.error ?? updateSchedule.error ?? null;
  const canSubmit =
    name.trim().length > 0 && workflowId.length > 0 && cronValid && !pending;

  function handleWorkflowChange(next: string) {
    setWorkflowId(next);
    if (!name.trim()) {
      const picked = workflows.find((w) => w.id === next);
      if (picked) setName(picked.name);
    }
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
      overlap,
      target: 'workflow',
      workflow_id: workflowId,
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
    workflowId,
    name,
    setName,
    cron,
    setCron,
    timezone,
    setTimezone,
    overlap,
    setOverlap,
    enabled,
    setEnabled,
    workflows,
    preview,
    cronValid,
    canSubmit,
    pending,
    error,
    isEdit: !!initial,
    submit,
    handleWorkflowChange,
    applyPreset,
  };
}

export type RecurringFormState = ReturnType<typeof useRecurringForm>;
