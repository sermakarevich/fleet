/**
 * Form state for the new-task panel.
 * Owns field values, coder/model/template lookups, recent cwds, open
 * tasks and submit/validation. Called by NewTaskPanel.
 */
import { useEffect, useMemo, useState } from 'react';
import { useCoders, useCreateTask, useTemplates, useTasks } from '../../../shared/hooks/useApi';
import type { CoderInfo, Template } from '../../../shared/types';

// Split a template body into title (first line) and description.
function splitTemplate(content: string): { title: string; description: string } {
  const lines = content.split('\n');
  return {
    title: lines[0].replace(/^#\s*/, '').trim(),
    description: lines.slice(1).join('\n').trim(),
  };
}

// All new-task form state plus submit and keyboard handling.
export function useNewTaskForm(onClose: () => void, onCreated: (id: string) => void) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [cwd, setCwd] = useState('');
  const [coder, setCoder] = useState('');
  const [model, setModel] = useState('');
  const [priority, setPriority] = useState('');
  const [args, setArgs] = useState('');
  const [dependencies, setDependencies] = useState<string[]>([]);
  const [titleError, setTitleError] = useState('');

  const { data: codersData } = useCoders();
  const { data: templatesData } = useTemplates();
  const { data: tasksData } = useTasks();
  const createTask = useCreateTask();

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

  async function submit() {
    if (!title.trim()) {
      setTitleError('Title is required');
      return;
    }
    setTitleError('');
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

  return {
    title, setTitle, description, setDescription, cwd, setCwd,
    coder, model, setModel, priority, setPriority, args, setArgs,
    dependencies, setDependencies, titleError,
    coders, templates, recentCwds, openTasks, createTask,
    submit, handleCoderChange, applyTemplate,
  };
}

export type NewTaskForm = ReturnType<typeof useNewTaskForm>;
