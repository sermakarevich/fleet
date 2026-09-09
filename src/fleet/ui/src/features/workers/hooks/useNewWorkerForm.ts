/**
 * Form state for the new-worker panel.
 * Owns field values, coder/model/template lookups, recent cwds, open
 * workers and submit/validation. "Run now" posts to POST /api/tasks;
 * "on a schedule" posts the same worker fields as a task-target schedule
 * (same payload shape as ScheduleForm). Called by NewWorkerPanel.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  useCoders,
  useCreateSchedule,
  useCreateTask,
  useCronPreview,
  useTasks,
  useTemplates,
} from '../../../shared/hooks/useApi';
import type { CoderInfo, Template } from '../../../shared/types';
import { buildTriggerPayload } from '../../triggers/useTriggerForm';

export type RunMode = 'now' | 'schedule';

// Split a template body into title (first line) and description.
function splitTemplate(content: string): { title: string; description: string } {
  const lines = content.split('\n');
  return {
    title: lines[0].replace(/^#\s*/, '').trim(),
    description: lines.slice(1).join('\n').trim(),
  };
}

// Browser time zone, falling back to UTC when unavailable.
function defaultTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC';
  } catch {
    return 'UTC';
  }
}

// All new-worker form state plus submit and keyboard handling.
export function useNewWorkerForm(onClose: () => void, onCreated: (id: string) => void) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [cwd, setCwd] = useState('');
  const [coder, setCoder] = useState('');
  const [model, setModel] = useState('');
  const [priority, setPriority] = useState('');
  const [args, setArgs] = useState('');
  const [dependencies, setDependencies] = useState<string[]>([]);
  const [titleError, setTitleError] = useState('');
  const [mode, setMode] = useState<RunMode>('now');
  const [scheduleName, setScheduleName] = useState('');
  const [cron, setCron] = useState('');
  const [timezone, setTimezone] = useState(defaultTimezone());
  const [overlap, setOverlap] = useState('skip');
  const [scheduleError, setScheduleError] = useState('');

  const { data: codersData } = useCoders();
  const { data: templatesData } = useTemplates();
  const { data: tasksData } = useTasks();
  const createTask = useCreateTask();
  const createSchedule = useCreateSchedule();
  const cronPreview = useCronPreview(cron, timezone);

  const coders: CoderInfo[] = codersData?.coders ?? [];
  const templates: Template[] = templatesData?.templates ?? [];

  const recentCwds = useMemo(() => {
    if (!tasksData) return [];
    const seen = new Set<string>();
    const cwds: string[] = [];
    for (const t of tasksData) {
      if (t.cwd && !seen.has(t.cwd)) {
        seen.add(t.cwd);
        cwds.push(t.cwd);
        if (cwds.length >= 10) break;
      }
    }
    return cwds;
  }, [tasksData]);

  const openTasks = useMemo(() => {
    if (!tasksData) return [];
    return tasksData.filter((t) => t.status !== 'closed' && t.status !== 'failed');
  }, [tasksData]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const cronValid = cronPreview.data?.valid === true;
  const pending = createTask.isPending || createSchedule.isPending;

  async function submitNow() {
    try {
      const result = await createTask.mutateAsync({
        title: title.trim(),
        description: description || undefined,
        cwd: cwd || undefined,
        coder: coder || undefined,
        model: model || undefined,
        priority: priority ? Number(priority) : undefined,
        args: args.trim() || undefined,
        dependencies: dependencies.length > 0 ? dependencies : undefined,
      });
      onCreated(result.id);
      onClose();
    } catch {
      // error displayed via createTask.error
    }
  }

  async function submitSchedule() {
    const name = scheduleName.trim() || title.trim();
    if (!cronValid) {
      setScheduleError('A valid cron expression is required');
      return;
    }
    setScheduleError('');
    try {
      // One payload shape for task schedules (TriggerForm's builder).
      const saved = await createSchedule.mutateAsync(buildTriggerPayload('task', {
        name,
        cron,
        timezone,
        enabled: true,
        overlap,
        title: title.trim(),
        description: description || '',
        cwd: cwd || '',
        coder: coder || '',
        model: model || '',
        priority: priority ? Number(priority) : 2,
        workflowId: '',
      }));
      onCreated(saved.id);
      onClose();
    } catch {
      // error displayed via createSchedule.error
    }
  }

  async function submit() {
    if (!title.trim()) {
      setTitleError('Title is required');
      return;
    }
    setTitleError('');
    if (mode === 'schedule') await submitSchedule();
    else await submitNow();
  }

  function handleCoderChange(name: string) {
    setCoder(name);
    const info = coders.find((c) => c.name === name);
    if (info?.default_model) setModel(info.default_model);
    else if (!name) setModel('');
  }

  function applyTemplate(t: Template) {
    const { title: first, description: rest } = splitTemplate(t.content);
    if (first) setTitle(first);
    setDescription(rest);
  }

  function applyPreset(expression: string) {
    setCron(expression);
  }

  return {
    title, setTitle, description, setDescription, cwd, setCwd,
    coder, model, setModel, priority, setPriority, args, setArgs,
    dependencies, setDependencies, titleError,
    mode, setMode, scheduleName, setScheduleName, cron, setCron,
    timezone, setTimezone, overlap, setOverlap, scheduleError,
    cronPreview, cronValid, pending,
    coders, templates, recentCwds, openTasks, createTask, createSchedule,
    submit, handleCoderChange, applyTemplate, applyPreset,
  };
}

export type NewWorkerForm = ReturnType<typeof useNewWorkerForm>;
