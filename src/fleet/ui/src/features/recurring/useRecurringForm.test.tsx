/**
 * Unit tests for the recurring form hook: submit stays disabled until a
 * workflow, a name and a valid cron are present, and submit posts
 * target "workflow" with a workflow_id and no title.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import type { Workflow } from '../../shared/types';
import { useRecurringForm } from './useRecurringForm';

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
    name: 'nightly-quality',
    description: '',
    defaults: { priority: 2 },
    stages: [],
    step_count: 3,
    stage_count: 2,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    run_count: 0,
    last_run: null,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useRecurringForm', () => {
  it('submit is disabled until a workflow, a name and a valid cron are present', async () => {
    vi.spyOn(api, 'listWorkflows').mockResolvedValue([makeWorkflow()]);
    const { result } = renderHook(
      () => useRecurringForm({ onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.canSubmit).toBe(false);
    act(() => {
      result.current.handleWorkflowChange('wf-1');
      result.current.setCron('0 9 * * 1-5');
    });
    // The cron preview fetch has no backend here, so the preview is not
    // valid and submit must stay disabled (cron required).
    expect(result.current.canSubmit).toBe(false);
  });

  it('submit posts target workflow with workflow_id and no title', async () => {
    vi.spyOn(api, 'listWorkflows').mockResolvedValue([makeWorkflow()]);
    vi.spyOn(api, 'previewCron').mockResolvedValue({
      valid: true,
      error: null,
      upcoming: ['2026-09-10T09:00:00Z'],
    });
    const createSpy = vi.spyOn(api, 'createSchedule').mockResolvedValue({
      id: 'sched-1',
      name: 'nightly-quality',
      cron: '0 9 * * 1-5',
      timezone: 'UTC',
      enabled: true,
      title: '',
      description: '',
      cwd: null,
      coder: null,
      model: null,
      priority: 2,
      overlap: 'skip',
      target: 'workflow',
      workflow_id: 'wf-1',
      created_at: '2026-09-01T00:00:00Z',
      updated_at: '2026-09-01T00:00:00Z',
      next_fire_at: null,
      run_count: 0,
      last_run: null,
    });
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const { result } = renderHook(() => useRecurringForm({ onSaved, onClose }), { wrapper });

    // Wait for the workflow list before picking, so the name default applies.
    await waitFor(() => expect(result.current.workflows).toHaveLength(1), { timeout: 5000 });
    act(() => {
      result.current.handleWorkflowChange('wf-1');
      result.current.setCron('0 9 * * 1-5');
    });
    // Picking a workflow defaults the name to the workflow name. The cron
    // preview is debounced, so wait for it to turn valid before submitting.
    expect(result.current.name).toBe('nightly-quality');
    await waitFor(() => expect(result.current.canSubmit).toBe(true), { timeout: 5000 });

    await act(async () => {
      await result.current.submit();
    });
    expect(createSpy).toHaveBeenCalledTimes(1);
    const payload = createSpy.mock.calls[0][0];
    expect(payload.target).toBe('workflow');
    expect(payload.workflow_id).toBe('wf-1');
    expect(payload).not.toHaveProperty('title');
    expect(payload).not.toHaveProperty('description');
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('create mode defaults to enabled with skip overlap', () => {
    vi.spyOn(api, 'listWorkflows').mockResolvedValue([]);
    const { result } = renderHook(
      () => useRecurringForm({ onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.isEdit).toBe(false);
    expect(result.current.enabled).toBe(true);
    expect(result.current.overlap).toBe('skip');
  });
});
