/**
 * Unit tests for the workflow editor hook: board edits, cross-stage
 * moves, needs scoping and the submit payload shape.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { api } from '../../shared/api';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import type { Workflow } from '../../shared/types';
import { useWorkflowEditor } from './useWorkflowEditor';

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}

function makeWorkflow(): Workflow {
  return {
    id: 'wf-1',
    name: 'nightly',
    description: 'Lint then report',
    defaults: { cwd: null, coder: null, model: null, priority: 2 },
    stages: [],
    step_count: 0,
    stage_count: 0,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    run_count: 0,
    last_run: null,
  };
}

beforeEach(() => {
  vi.spyOn(api, 'validateWorkflow').mockResolvedValue({ valid: true, problems: [] });
  vi.spyOn(api, 'getCoders').mockResolvedValue({ coders: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useWorkflowEditor', () => {
  it('add stage and step grows the board', () => {
    const { result } = renderHook(
      () => useWorkflowEditor({ initial: null, onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.stages).toHaveLength(1);
    act(() => {
      result.current.addStage();
    });
    expect(result.current.stages).toHaveLength(2);
    act(() => {
      result.current.addStep(0);
    });
    expect(result.current.stages[0]?.steps).toHaveLength(1);
    expect(result.current.stages[0]?.steps[0]?.name).toBe('step-1');
  });

  it('move step between stages updates its stage index', () => {
    const { result } = renderHook(
      () => useWorkflowEditor({ initial: null, onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    act(() => {
      result.current.addStage();
      result.current.addStep(0);
    });
    act(() => {
      result.current.moveStepAcross(0, 0, 1);
    });
    expect(result.current.stages[0]?.steps).toHaveLength(0);
    expect(result.current.stages[1]?.steps.map((s) => s.name)).toEqual(['step-1']);
  });

  it('needs options exclude same and later stages', () => {
    const { result } = renderHook(
      () => useWorkflowEditor({ initial: null, onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    act(() => {
      result.current.addStage();
      result.current.addStage();
      result.current.addStep(0);
      result.current.addStep(1);
      result.current.addStep(2);
    });
    const first = result.current.stages[0]?.steps[0]?.name as string;
    const second = result.current.stages[1]?.steps[0]?.name as string;
    const third = result.current.stages[2]?.steps[0]?.name as string;
    expect(result.current.needsOptions(0)).toEqual([]);
    expect(result.current.needsOptions(1)).toEqual([first]);
    expect(result.current.needsOptions(1)).not.toContain(second);
    expect(result.current.needsOptions(1)).not.toContain(third);
    expect(result.current.needsOptions(2)).toEqual([first, second]);
  });

  it('submit payload shape matches the workflow request', async () => {
    const saved = { ...makeWorkflow(), name: 'nightly' };
    const createSpy = vi.spyOn(api, 'createWorkflow').mockResolvedValue(saved);
    const onSaved = vi.fn();
    const { result } = renderHook(
      () => useWorkflowEditor({ initial: null, onSaved, onClose: () => undefined }),
      { wrapper },
    );
    act(() => {
      result.current.setName('nightly');
      result.current.addStep(0);
    });
    act(() => {
      result.current.updateStep(0, 0, { title: 'Lint everything' });
    });
    let out: Workflow | null = null;
    await act(async () => {
      out = await result.current.save();
    });
    expect(createSpy).toHaveBeenCalledWith({
      name: 'nightly',
      description: undefined,
      defaults: undefined,
      stages: [
        {
          name: 'stage-1',
          steps: [
            {
              name: 'step-1',
              title: 'Lint everything',
              description: undefined,
              cwd: undefined,
              coder: undefined,
              model: undefined,
              priority: undefined,
              needs: undefined,
            },
          ],
        },
      ],
    });
    expect(out).toEqual(saved);
    expect(onSaved).toHaveBeenCalledWith(saved);
  });
});
