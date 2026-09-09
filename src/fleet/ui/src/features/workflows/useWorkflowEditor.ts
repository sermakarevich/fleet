/**
 * Draft state for the workflow stage/step board editor.
 * Owns header fields, defaults, stages and steps, live server validation
 * (debounced) and create/update/run submit. Called by WorkflowEditor;
 * tested in useWorkflowEditor.test.ts.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  useCoders,
  useCreateWorkflow,
  useRunWorkflow,
  useUpdateWorkflow,
  useValidateWorkflow,
} from '../../shared/hooks/useApi';
import { useDebounced } from '../../shared/hooks/useDebounced';
import type { CoderInfo, Workflow, WorkflowInput } from '../../shared/types';

// One step card in the draft; empty strings mean "use the workflow default".
export interface StepDraft {
  name: string;
  title: string;
  description: string;
  cwd: string;
  coder: string;
  model: string;
  priority: string;
  needs: string[];
}

// One stage column in the draft.
export interface StageDraft {
  name: string;
  steps: StepDraft[];
}

interface Options {
  /** Pre-fill source for edit mode; null means create mode. */
  initial: Workflow | null;
  /** Run after a successful save (page navigates to the editor/away). */
  onSaved: (workflow: Workflow) => void;
  /** Close the editor without saving. */
  onClose: () => void;
}

// Blank step with a unique name inside the draft.
function blankStep(taken: Set<string>): StepDraft {
  let n = taken.size + 1;
  let name = `step-${n}`;
  while (taken.has(name)) {
    n += 1;
    name = `step-${n}`;
  }
  return { name, title: '', description: '', cwd: '', coder: '', model: '', priority: '', needs: [] };
}

// All step names in the draft.
function draftStepNames(stages: StageDraft[]): Set<string> {
  return new Set(stages.flatMap((s) => s.steps.map((t) => t.name)));
}

// Step names from stages before `stageIndex` (the only valid `needs`).
export function earlierStepNames(stages: StageDraft[], stageIndex: number): string[] {
  return stages.slice(0, stageIndex).flatMap((s) => s.steps.map((t) => t.name));
}

// Draft stages from a saved workflow (edit mode pre-fill).
function stagesFromWorkflow(workflow: Workflow): StageDraft[] {
  return (workflow.stages ?? []).map((stage) => ({
    name: stage.name,
    steps: (stage.steps ?? []).map((step) => ({
      name: step.name,
      title: step.title,
      description: step.description ?? '',
      cwd: step.cwd ?? '',
      coder: step.coder ?? '',
      model: step.model ?? '',
      priority: step.priority == null ? '' : String(step.priority),
      needs: step.needs ?? [],
    })),
  }));
}

// Text-field priority to a number; blank or garbage means "unset".
function parsePriority(raw: string): number | undefined {
  if (raw.trim() === '') return undefined;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

// All editor state plus validation and submit.
export function useWorkflowEditor({ initial, onSaved, onClose }: Options) {
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [defCwd, setDefCwd] = useState(initial?.defaults.cwd ?? '');
  const [defCoder, setDefCoder] = useState(initial?.defaults.coder ?? '');
  const [defModel, setDefModel] = useState(initial?.defaults.model ?? '');
  const [defPriority, setDefPriority] = useState(
    initial?.defaults.priority == null ? '' : String(initial.defaults.priority),
  );
  const [stages, setStages] = useState<StageDraft[]>(
    () => (initial ? stagesFromWorkflow(initial) : [{ name: 'stage-1', steps: [] }]),
  );

  const { data: codersData } = useCoders();
  const createWorkflow = useCreateWorkflow();
  const updateWorkflow = useUpdateWorkflow();
  const runWorkflow = useRunWorkflow();
  const validate = useValidateWorkflow();
  const [problems, setProblems] = useState<string[]>([]);

  const coders: CoderInfo[] = codersData?.coders ?? [];
  const pending = createWorkflow.isPending || updateWorkflow.isPending || runWorkflow.isPending;
  const error = createWorkflow.error ?? updateWorkflow.error ?? null;

  // Submit payload, rebuilt every render and validated debounced.
  const payload: WorkflowInput = useMemo(() => {
    const defaults: WorkflowInput['defaults'] = {};
    if (defCwd) defaults.cwd = defCwd;
    if (defCoder) defaults.coder = defCoder;
    if (defModel) defaults.model = defModel;
    const priority = parsePriority(defPriority);
    if (priority !== undefined) defaults.priority = priority;
    return {
      name: name.trim(),
      description: description || undefined,
      defaults: Object.keys(defaults).length > 0 ? defaults : undefined,
      stages: stages.map((stage) => ({
        name: stage.name.trim() || 'stage',
        steps: stage.steps.map((step) => ({
          name: step.name.trim(),
          title: step.title,
          description: step.description || undefined,
          cwd: step.cwd || undefined,
          coder: step.coder || undefined,
          model: step.model || undefined,
          priority: parsePriority(step.priority),
          needs: step.needs.length > 0 ? step.needs : undefined,
        })),
      })),
    };
  }, [name, description, defCwd, defCoder, defModel, defPriority, stages]);

  const debouncedKey = useDebounced(JSON.stringify(payload));
  useEffect(() => {
    let live = true;
    validate
      .mutateAsync(JSON.parse(debouncedKey) as WorkflowInput)
      .then((result) => {
        if (live) setProblems(result.problems);
      })
      .catch(() => {
        // No backend in tests or offline: keep the last problems.
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedKey]);
  const validating = validate.isPending;

  const canSubmit = name.trim().length > 0 && problems.length === 0 && !pending;

  function updateStage(index: number, patch: Partial<StageDraft>) {
    setStages((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }

  function updateStep(stageIndex: number, stepIndex: number, patch: Partial<StepDraft>) {
    setStages((prev) =>
      prev.map((s, i) =>
        i !== stageIndex
          ? s
          : { ...s, steps: s.steps.map((t, j) => (j === stepIndex ? { ...t, ...patch } : t)) },
      ),
    );
  }

  function addStage() {
    setStages((prev) => [...prev, { name: `stage-${prev.length + 1}`, steps: [] }]);
  }

  function removeStage(index: number) {
    setStages((prev) => {
      if ((prev[index]?.steps.length ?? 0) > 0) return prev;
      return prev.filter((_, i) => i !== index);
    });
  }

  function moveStage(index: number, direction: -1 | 1) {
    setStages((prev) => {
      const target = index + direction;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target] as StageDraft, next[index] as StageDraft];
      return next;
    });
  }

  function addStep(stageIndex: number) {
    setStages((prev) => {
      const step = blankStep(draftStepNames(prev));
      return prev.map((s, i) => (i === stageIndex ? { ...s, steps: [...s.steps, step] } : s));
    });
  }

  function removeStep(stageIndex: number, stepIndex: number) {
    setStages((prev) =>
      prev.map((s, i) =>
        i !== stageIndex ? s : { ...s, steps: s.steps.filter((_, j) => j !== stepIndex) },
      ),
    );
  }

  function duplicateStep(stageIndex: number, stepIndex: number) {
    setStages((prev) => {
      const taken = draftStepNames(prev);
      return prev.map((s, i) => {
        if (i !== stageIndex) return s;
        const source = s.steps[stepIndex];
        if (!source) return s;
        let copyName = `${source.name}-copy`;
        let n = 2;
        while (taken.has(copyName)) {
          copyName = `${source.name}-copy-${n}`;
          n += 1;
        }
        taken.add(copyName);
        const copy: StepDraft = { ...source, name: copyName, needs: [...source.needs] };
        const steps = [...s.steps];
        steps.splice(stepIndex + 1, 0, copy);
        return { ...s, steps };
      });
    });
  }

  function moveStepUpDown(stageIndex: number, stepIndex: number, direction: -1 | 1) {
    setStages((prev) =>
      prev.map((s, i) => {
        if (i !== stageIndex) return s;
        const target = stepIndex + direction;
        if (target < 0 || target >= s.steps.length) return s;
        const steps = [...s.steps];
        [steps[stepIndex], steps[target]] = [steps[target] as StepDraft, steps[stepIndex] as StepDraft];
        return { ...s, steps };
      }),
    );
  }

  // Move a step to the neighbouring stage; `needs` that no longer point
  // at earlier stages are dropped so the draft stays valid.
  function moveStepAcross(stageIndex: number, stepIndex: number, direction: -1 | 1) {
    setStages((prev) => {
      const target = stageIndex + direction;
      if (target < 0 || target >= prev.length) return prev;
      const source = prev[stageIndex];
      const step = source?.steps[stepIndex];
      if (!source || !step) return prev;
      const allowed = new Set(
        prev.slice(0, target).flatMap((s) => s.steps.map((t) => t.name)),
      );
      const moved: StepDraft = { ...step, needs: step.needs.filter((n) => allowed.has(n)) };
      return prev.map((s, i) => {
        if (i === stageIndex) return { ...s, steps: s.steps.filter((_, j) => j !== stepIndex) };
        if (i === target) return { ...s, steps: [...s.steps, moved] };
        return s;
      });
    });
  }

  function toggleNeed(stageIndex: number, stepIndex: number, dep: string) {
    setStages((prev) =>
      prev.map((s, i) => {
        if (i !== stageIndex) return s;
        return {
          ...s,
          steps: s.steps.map((t, j) => {
            if (j !== stepIndex) return t;
            const needs = t.needs.includes(dep) ? t.needs.filter((n) => n !== dep) : [...t.needs, dep];
            return { ...t, needs };
          }),
        };
      }),
    );
  }

  // Candidate `needs` for a step: names from earlier stages only.
  function needsOptions(stageIndex: number): string[] {
    return earlierStepNames(stages, stageIndex);
  }

  function handleCoderChange(next: string) {
    setDefCoder(next);
    const info = coders.find((c) => c.name === next);
    if (info?.default_model) setDefModel(info.default_model);
    else if (!next) setDefModel('');
  }

  async function save(): Promise<Workflow | null> {
    if (!canSubmit) return null;
    try {
      const saved = initial
        ? await updateWorkflow.mutateAsync({ id: initial.id, payload })
        : await createWorkflow.mutateAsync(payload);
      onSaved(saved);
      return saved;
    } catch {
      // error surfaces via the mutation's error state in the form
      return null;
    }
  }

  async function saveAndRun(): Promise<void> {
    const saved = await save();
    if (!saved) return;
    try {
      await runWorkflow.mutateAsync(saved.id);
    } catch {
      // the run toast already reports the failure
    }
  }

  return {
    name, setName, description, setDescription,
    defCwd, setDefCwd, defCoder, defModel, setDefModel, defPriority, setDefPriority,
    stages, setStageName: (i: number, v: string) => updateStage(i, { name: v }),
    updateStep, addStage, removeStage, moveStage,
    addStep, removeStep, duplicateStep, moveStepUpDown, moveStepAcross,
    toggleNeed, needsOptions,
    coders, problems, validating, canSubmit, pending, error,
    payload, isEdit: !!initial,
    save, saveAndRun, onClose,
    handleCoderChange,
  };
}

export type WorkflowEditorState = ReturnType<typeof useWorkflowEditor>;
