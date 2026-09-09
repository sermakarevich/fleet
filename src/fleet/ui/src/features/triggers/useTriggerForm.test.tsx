/**
 * Unit tests for the trigger form hook and its payload builder: submit
 * stays disabled until the form is valid, edit mode pre-fills every
 * field, and the built payload for both targets matches the schedules
 * API request model (keys checked against a ScheduleView fixture typed
 * from the generated OpenAPI client).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import type { components } from '../../shared/api-types.gen';
import type { Schedule, Workflow } from '../../shared/types';
import { buildTriggerPayload, useTriggerForm } from './useTriggerForm';

type ScheduleView = components['schemas']['ScheduleView'];

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

// Schedule fixture typed from the generated OpenAPI client: the one
// shape both the API and the UI agree on.
function makeScheduleView(overrides: Partial<ScheduleView> = {}): ScheduleView {
  return {
    id: 'sched-9',
    name: 'nightly-triage',
    cron: '0 9 * * 1-5',
    timezone: 'Europe/Warsaw',
    enabled: true,
    title: 'Triage {date}',
    description: 'Look at the inbox',
    cwd: '/repo',
    coder: 'claude',
    model: 'sonnet',
    priority: 2,
    overlap: 'skip',
    target: 'task',
    workflow_id: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    next_fire_at: null,
    run_count: 0,
    last_run: null,
    ...overrides,
  };
}

function makeSchedule(overrides: Partial<Schedule> = {}): Schedule {
  return makeScheduleView(overrides) as Schedule;
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

describe('buildTriggerPayload', () => {
  it('shapes a task-target request with the worker fields', () => {
    const payload = buildTriggerPayload('task', {
      name: 'nightly-triage',
      cron: '0 9 * * 1-5',
      timezone: 'Europe/Warsaw',
      enabled: true,
      overlap: 'skip',
      title: 'Triage {date}',
      description: 'Look at the inbox',
      cwd: '/repo',
      coder: 'claude',
      model: 'sonnet',
      priority: 2,
      workflowId: '',
    });
    expect(payload).toEqual({
      name: 'nightly-triage',
      cron: '0 9 * * 1-5',
      timezone: 'Europe/Warsaw',
      enabled: true,
      overlap: 'skip',
      target: 'task',
      title: 'Triage {date}',
      description: 'Look at the inbox',
      cwd: '/repo',
      coder: 'claude',
      model: 'sonnet',
      priority: 2,
    });
    // Every payload key exists on the API's schedule model.
    const fixtureKeys = new Set(Object.keys(makeScheduleView()));
    for (const key of Object.keys(payload)) {
      expect(fixtureKeys.has(key)).toBe(true);
    }
  });

  it('shapes a workflow-target request with workflow_id and no worker fields', () => {
    const payload = buildTriggerPayload('workflow', {
      name: 'nightly-quality',
      cron: '0 9 * * 1-5',
      timezone: 'UTC',
      enabled: true,
      overlap: 'queue',
      title: '',
      description: '',
      cwd: '',
      coder: '',
      model: '',
      priority: 2,
      workflowId: 'wf-1',
    });
    expect(payload).toEqual({
      name: 'nightly-quality',
      cron: '0 9 * * 1-5',
      timezone: 'UTC',
      enabled: true,
      overlap: 'queue',
      target: 'workflow',
      workflow_id: 'wf-1',
    });
    expect(payload).not.toHaveProperty('title');
    expect(payload).not.toHaveProperty('description');
    const fixtureKeys = new Set(Object.keys(makeScheduleView({ target: 'workflow', workflow_id: 'wf-1' })));
    for (const key of Object.keys(payload)) {
      expect(fixtureKeys.has(key)).toBe(true);
    }
  });
});

describe('useTriggerForm task target', () => {
  it('submit is disabled until name, valid cron and title are present', () => {
    const { result } = renderHook(
      () => useTriggerForm({ target: 'task', onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.canSubmit).toBe(false);
    act(() => {
      result.current.setName('nightly');
      result.current.setTitle('Triage {date}');
      result.current.setCron('0 9 * * 1-5');
    });
    // The cron preview fetch has no backend here, so the preview is not
    // valid and submit must stay disabled.
    expect(result.current.canSubmit).toBe(false);
  });

  it('edit mode pre-fills from the schedule', () => {
    const schedule = makeSchedule({ enabled: false, overlap: 'queue' });
    const { result } = renderHook(
      () => useTriggerForm({ target: 'task', initial: schedule, onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.isEdit).toBe(true);
    expect(result.current.name).toBe('nightly-triage');
    expect(result.current.cron).toBe('0 9 * * 1-5');
    expect(result.current.timezone).toBe('Europe/Warsaw');
    expect(result.current.title).toBe('Triage {date}');
    expect(result.current.description).toBe('Look at the inbox');
    expect(result.current.cwd).toBe('/repo');
    expect(result.current.coder).toBe('claude');
    expect(result.current.model).toBe('sonnet');
    expect(result.current.priority).toBe(2);
    expect(result.current.overlap).toBe('queue');
    expect(result.current.enabled).toBe(false);
  });

  it('create mode defaults to enabled with skip overlap', () => {
    const { result } = renderHook(
      () => useTriggerForm({ target: 'task', onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.isEdit).toBe(false);
    expect(result.current.enabled).toBe(true);
    expect(result.current.overlap).toBe('skip');
  });

  it('submit posts target task with the worker fields', async () => {
    vi.spyOn(api, 'getCoders').mockResolvedValue({ coders: [] });
    vi.spyOn(api, 'previewCron').mockResolvedValue({
      valid: true,
      error: null,
      upcoming: ['2026-09-10T09:00:00Z'],
    });
    const createSpy = vi.spyOn(api, 'createSchedule').mockResolvedValue(makeSchedule());
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const { result } = renderHook(
      () => useTriggerForm({ target: 'task', onSaved, onClose }),
      { wrapper },
    );

    act(() => {
      result.current.setName('nightly');
      result.current.setTitle('Triage {date}');
      result.current.setCron('0 9 * * 1-5');
    });
    await waitFor(() => expect(result.current.canSubmit).toBe(true), { timeout: 5000 });

    await act(async () => {
      await result.current.submit();
    });
    expect(createSpy).toHaveBeenCalledTimes(1);
    const payload = createSpy.mock.calls[0][0];
    expect(payload.target).toBe('task');
    expect(payload.title).toBe('Triage {date}');
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});

describe('useTriggerForm workflow target', () => {
  it('submit is disabled until a workflow, a name and a valid cron are present', () => {
    vi.spyOn(api, 'listWorkflows').mockResolvedValue([makeWorkflow()]);
    const { result } = renderHook(
      () => useTriggerForm({ target: 'workflow', onSaved: () => undefined, onClose: () => undefined }),
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
    const createSpy = vi.spyOn(api, 'createSchedule').mockResolvedValue(
      makeSchedule({ target: 'workflow', workflow_id: 'wf-1' }),
    );
    const onSaved = vi.fn();
    const onClose = vi.fn();
    const { result } = renderHook(
      () => useTriggerForm({ target: 'workflow', onSaved, onClose }),
      { wrapper },
    );

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
});
