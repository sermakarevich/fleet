/**
 * Unit tests for the trigger table: one table renders both targets with
 * the right Target-detail cell, the workflow-only Overlap column, and
 * last-run chips linking to the worker or the workflow run.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import { formatShortDateTime } from '../../shared/format';
import type { Schedule, Workflow } from '../../shared/types';
import { TriggerTable } from './TriggerTable';

afterEach(cleanup);

function wrapper(initialEntries: string[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  };
}

// Minimal schedule; tests override target and detail fields.
function makeSchedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    id: 'sched-1',
    name: 'nightly',
    cron: '0 9 * * 1-5',
    timezone: 'UTC',
    enabled: true,
    title: 'Triage {date}',
    description: '',
    cwd: null,
    coder: 'claude',
    model: 'sonnet',
    priority: 1,
    overlap: 'skip',
    target: 'task',
    workflow_id: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    next_fire_at: '2026-09-10T09:00:00Z',
    run_count: 3,
    last_run: null,
    ...overrides,
  };
}

function taskLastRun() {
  return {
    schedule_id: 'sched-1',
    n: 3,
    scheduled_for: '2026-09-09T09:00:00Z',
    fired_at: '2026-09-09T09:00:01Z',
    trigger: 'cron',
    task_id: 'task-1',
    skipped: false,
    reason: '',
    task_status: 'closed',
    task_title: 'Triage',
    workflow_run_id: null,
    workflow_run_status: null,
  };
}

function workflowLastRun() {
  return {
    ...taskLastRun(),
    task_id: null,
    task_status: null,
    workflow_run_id: 'run-9',
    workflow_run_status: 'succeeded',
  };
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

beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
  vi.spyOn(api, 'listWorkflows').mockResolvedValue([makeWorkflow()]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('TriggerTable task target', () => {
  it('fetches task schedules and shows the coder·model detail without an Overlap column', async () => {
    const listSpy = vi.spyOn(api, 'getSchedules').mockResolvedValue([
      makeSchedule({ id: 's1', name: 'nightly-triage', last_run: taskLastRun() }),
    ]);
    render(<TriggerTable target="task" />, { wrapper: wrapper(['/workers?tab=scheduled']) });

    expect(await screen.findByText('nightly-triage')).toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledWith('task');
    // Target detail is coder·model for task schedules.
    expect(screen.getByText('claude·sonnet')).toBeInTheDocument();
    expect(screen.queryByText('Overlap')).not.toBeInTheDocument();
    expect(screen.getByText(formatShortDateTime('2026-09-10T09:00:00Z'))).toBeInTheDocument();
    // Last-run chip links to the worker.
    const chip = screen.getByText('Closed');
    expect(chip.closest('a')?.getAttribute('href')).toBe('/workers/task-1');
  });

  it('renders the empty state when there are no task schedules', async () => {
    vi.spyOn(api, 'getSchedules').mockResolvedValue([]);
    render(<TriggerTable target="task" />, { wrapper: wrapper(['/workers?tab=scheduled']) });
    expect(await screen.findByText(/No scheduled workers yet/)).toBeInTheDocument();
  });
});

describe('TriggerTable workflow target', () => {
  it('fetches workflow schedules and shows the workflow name plus Overlap', async () => {
    const listSpy = vi.spyOn(api, 'getSchedules').mockResolvedValue([
      makeSchedule({
        id: 's2',
        name: 'quality-schedule',
        target: 'workflow',
        workflow_id: 'wf-1',
        coder: null,
        model: null,
        last_run: workflowLastRun(),
      }),
    ]);
    render(<TriggerTable target="workflow" />, { wrapper: wrapper(['/workflows?tab=scheduled']) });

    expect(await screen.findByText('quality-schedule')).toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledWith('workflow');
    // Target detail is the linked workflow name for workflow schedules.
    const workflowLink = screen.getByText('nightly-quality', { selector: 'a' });
    expect(workflowLink.getAttribute('href')).toBe('/workflows/wf-1');
    expect(screen.getByText('Overlap')).toBeInTheDocument();
    // Last-run chip links to the workflow run.
    const chip = screen.getByText('Succeeded');
    expect(chip.closest('a')?.getAttribute('href')).toBe('/workflow-runs/run-9');
  });

  it('renders "never" and "skipped" last runs and the empty state', async () => {
    vi.spyOn(api, 'getSchedules').mockResolvedValue([
      makeSchedule({ id: 's3', name: 'never-ran', target: 'workflow', workflow_id: 'wf-1' }),
      makeSchedule({
        id: 's4',
        name: 'was-skipped',
        target: 'workflow',
        workflow_id: 'wf-1',
        last_run: { ...workflowLastRun(), skipped: true, workflow_run_id: null },
      }),
    ]);
    render(<TriggerTable target="workflow" />, { wrapper: wrapper(['/workflows?tab=scheduled']) });

    await screen.findByText('never-ran');
    expect(screen.getByText('never')).toBeInTheDocument();
    expect(screen.getByText('skipped')).toBeInTheDocument();
  });

  it('renders the empty state when there are no workflow schedules', async () => {
    vi.spyOn(api, 'getSchedules').mockResolvedValue([]);
    render(<TriggerTable target="workflow" />, { wrapper: wrapper(['/workflows?tab=scheduled']) });
    expect(await screen.findByText(/No recurring workflows/)).toBeInTheDocument();
  });

  it('shows a workflow schedule inputs in the row', async () => {
    vi.spyOn(api, 'getSchedules').mockResolvedValue([
      makeSchedule({
        id: 's5',
        name: 'paper-schedule',
        target: 'workflow',
        workflow_id: 'wf-1',
        coder: null,
        model: null,
        inputs: { url: 'https://example.com/paper' },
      }),
    ]);
    render(<TriggerTable target="workflow" />, { wrapper: wrapper(['/workflows?tab=scheduled']) });

    expect(await screen.findByText('paper-schedule')).toBeInTheDocument();
    expect(screen.getByText('Inputs')).toBeInTheDocument();
    const cell = screen.getByText('url=https://example.com/paper');
    expect(cell).toHaveAttribute('title', 'url=https://example.com/paper');
  });
});

describe('TriggerTable polling', () => {
  it('waits for both schedule targets without cross-talk', async () => {
    const listSpy = vi.spyOn(api, 'getSchedules').mockImplementation(async (target) => [
      makeSchedule({ id: `only-${target}`, name: `name-${target}`, target: target ?? 'task' }),
    ]);
    const { unmount } = render(<TriggerTable target="task" />, {
      wrapper: wrapper(['/workers?tab=scheduled']),
    });
    expect(await screen.findByText('name-task')).toBeInTheDocument();
    unmount();
    render(<TriggerTable target="workflow" />, { wrapper: wrapper(['/workflows?tab=scheduled']) });
    expect(await screen.findByText('name-workflow')).toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledWith('task');
    expect(listSpy).toHaveBeenCalledWith('workflow');
  });
});
