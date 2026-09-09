/**
 * Form state for the trigger create/edit modal, parameterised by target.
 * Owns field values, cron preview validity, coder/workflow lookups and
 * create/update submit; buildTriggerPayload is the one place that shapes
 * a schedule request (NewWorkerPanel's schedule mode reuses it).
 * Called by TriggerForm.
 */
import { useState } from 'react';
import {
  useCoders,
  useCreateSchedule,
  useCronPreview,
  useUpdateSchedule,
  useWorkflows,
} from '../../shared/hooks/useApi';
import type { CoderInfo, Schedule, ScheduleInput, Workflow } from '../../shared/types';
import type { TriggerTarget } from './types';

// Browser time zone, falling back to UTC when unavailable.
export function defaultTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC';
  } catch {
    return 'UTC';
  }
}

// Raw field values the payload builder reads (hook state or a caller form).
export interface TriggerPayloadFields {
  name: string;
  cron: string;
  timezone: string;
  enabled: boolean;
  overlap: string;
  title: string;
  description: string;
  cwd: string;
  coder: string;
  model: string;
  priority: number;
  workflowId: string;
  // Run inputs for the target workflow; omitted for task schedules.
  inputs?: Record<string, string>;
}

// The one place that shapes a schedule request: task targets carry the
// worker fields with target "task"; workflow targets carry only the
// workflow_id plus the workflow's run inputs with target "workflow"
// (backend requires one side each).
export function buildTriggerPayload(target: TriggerTarget, f: TriggerPayloadFields): ScheduleInput {
  const shared = {
    name: f.name.trim(),
    cron: f.cron.trim(),
    timezone: f.timezone.trim() || undefined,
    enabled: f.enabled,
    overlap: f.overlap,
  };
  if (target === 'workflow') {
    const inputs: Record<string, string> = {};
    for (const [key, value] of Object.entries(f.inputs ?? {})) {
      if (value !== '') inputs[key] = value;
    }
    return {
      ...shared,
      target: 'workflow',
      workflow_id: f.workflowId,
      inputs: Object.keys(inputs).length > 0 ? inputs : undefined,
    };
  }
  return {
    ...shared,
    target: 'task',
    title: f.title.trim(),
    description: f.description || undefined,
    cwd: f.cwd || undefined,
    coder: f.coder || undefined,
    model: f.model || undefined,
    priority: f.priority,
  };
}

// Declared inputs of one workflow (ADR 0010): the schedule form asks for
// these when its target workflow declares them.
export function workflowInputs(workflow: Workflow | undefined): Array<{
  name: string; description: string; required: boolean; default: string | null;
}> {
  return (workflow?.inputs ?? []).map((input) => ({
    name: input.name,
    description: input.description ?? '',
    required: input.required ?? false,
    default: input.default ?? null,
  }));
}

// Label for the workflow picker: name plus its stage count.
export function workflowOptionLabel(workflow: Workflow): string {
  return `${workflow.name} · ${workflow.stage_count} stage${workflow.stage_count === 1 ? '' : 's'}`;
}

interface Options {
  /** Which schedule kind this form edits (task worker or workflow run). */
  target: TriggerTarget;
  /** Pre-fill source for edit mode; null/undefined means create mode. */
  initial?: Schedule | null;
  /** Run after a successful save (table navigates, drawer refreshes). */
  onSaved: (schedule: Schedule) => void;
  /** Close the modal. */
  onClose: () => void;
}

// All trigger-form state plus validation and submit.
export function useTriggerForm({ target, initial, onSaved, onClose }: Options) {
  const [name, setName] = useState(initial?.name ?? '');
  const [cron, setCron] = useState(initial?.cron ?? '');
  const [timezone, setTimezone] = useState(initial?.timezone ?? defaultTimezone());
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [overlap, setOverlap] = useState(initial?.overlap ?? 'skip');
  const [title, setTitle] = useState(initial?.title ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [cwd, setCwd] = useState(initial?.cwd ?? '');
  const [coder, setCoder] = useState(initial?.coder ?? '');
  const [model, setModel] = useState(initial?.model ?? '');
  const [priority, setPriority] = useState(initial?.priority ?? 2);
  const [workflowId, setWorkflowId] = useState(initial?.workflow_id ?? '');
  // Values for the target workflow's declared inputs (workflow schedules).
  // Pre-filled from the schedule, then from each input's default.
  const [inputs, setInputs] = useState<Record<string, string>>(() => ({ ...(initial?.inputs ?? {}) }));

  const { data: codersData } = useCoders();
  const { data: workflowsData } = useWorkflows();
  const preview = useCronPreview(cron, timezone);
  const createSchedule = useCreateSchedule();
  const updateSchedule = useUpdateSchedule();

  const coders: CoderInfo[] = codersData?.coders ?? [];
  const workflows: Workflow[] = workflowsData ?? [];
  const targetWorkflow = workflows.find((w) => w.id === workflowId);
  const decls = target === 'workflow' ? workflowInputs(targetWorkflow) : [];
  // Effective value: typed value wins, else the input's default, else blank.
  function inputValue(name: string, fallback: string | null): string {
    const current = inputs[name];
    if (current !== undefined) return current;
    return fallback ?? '';
  }
  const missingInputs = decls.filter((decl) => decl.required && !inputValue(decl.name, decl.default).trim());
  const cronValid = preview.data?.valid === true;
  const pending = createSchedule.isPending || updateSchedule.isPending;
  const error = createSchedule.error ?? updateSchedule.error ?? null;
  const canSubmit =
    target === 'workflow'
      ? name.trim().length > 0 && workflowId.length > 0 && cronValid && missingInputs.length === 0 && !pending
      : name.trim().length > 0 && title.trim().length > 0 && cronValid && !pending;

  function setInput(name: string, value: string) {
    setInputs((prev) => ({ ...prev, [name]: value }));
  }

  function handleCoderChange(next: string) {
    setCoder(next);
    const info = coders.find((c) => c.name === next);
    if (info?.default_model) setModel(info.default_model);
    else if (!next) setModel('');
  }

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
    // Resolve each declared input: typed value, else its default, else skip
    // (required ones are guaranteed present by canSubmit).
    const resolved: Record<string, string> = {};
    for (const decl of decls) {
      const value = inputValue(decl.name, decl.default);
      if (value !== '') resolved[decl.name] = value;
    }
    const payload = buildTriggerPayload(target, {
      name, cron, timezone, enabled, overlap,
      title, description, cwd, coder, model, priority, workflowId,
      inputs: resolved,
    });
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
    enabled, setEnabled, overlap, setOverlap,
    title, setTitle, description, setDescription, cwd, setCwd,
    coder, model, setModel, priority, setPriority,
    workflowId, workflows,
    decls, inputs, setInput, inputValue, missingInputs,
    coders, preview, cronValid, canSubmit, pending, error,
    isEdit: !!initial,
    submit, handleCoderChange, handleWorkflowChange, applyPreset,
  };
}

export type TriggerFormState = ReturnType<typeof useTriggerForm>;
