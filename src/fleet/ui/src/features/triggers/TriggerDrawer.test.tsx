/**
 * Unit tests for the trigger drawer: the task variant shows the worker
 * template and links runs to workers; the workflow variant shows the
 * linked workflow and past workflow runs.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import type { ScheduleDetail, Workflow } from '../../shared/types';
import { TriggerDrawer } from './TriggerDrawer';

afterEach(cleanup);

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function makeDetail(overrides: Partial<ScheduleDetail> = {}): ScheduleDetail {
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
    model: null,
    priority: 1,
    overlap: 'skip',
    target: 'task',
    workflow_id: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    next_fire_at: null,
    run_count: 1,
    last_run: null,
    upcoming: ['2026-09-10T09:00:00Z'],
    runs: [
      {
        schedule_id: 'sched-1',
        n: 1,
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
      },
    ],
    ...overrides,
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
  vi.spyOn(api, 'listWorkflows').mockResolvedValue([makeWorkflow()]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('TriggerDrawer', () => {
  it('task target shows the title template and links the run to the worker', async () => {
    vi.spyOn(api, 'getSchedule').mockResolvedValue(makeDetail());
    render(<TriggerDrawer target="task" scheduleId="sched-1" onClose={() => {}} />, { wrapper });

    expect(await screen.findByText('Title template')).toBeInTheDocument();
    expect(screen.getByText('Triage {date}')).toBeInTheDocument();
    const runLink = screen.getByText('task-1').closest('a');
    expect(runLink?.getAttribute('href')).toBe('/workers/task-1');
    expect(screen.getByRole('button', { name: 'Run now' })).toBeInTheDocument();
  });

  it('workflow target shows the linked workflow and past workflow runs', async () => {
    vi.spyOn(api, 'getSchedule').mockResolvedValue(
      makeDetail({
        name: 'nightly-quality',
        target: 'workflow',
        workflow_id: 'wf-1',
        runs: [
          {
            schedule_id: 'sched-1',
            n: 1,
            scheduled_for: '2026-09-09T09:00:00Z',
            fired_at: '2026-09-09T09:00:01Z',
            trigger: 'cron',
            task_id: null,
            skipped: false,
            reason: '',
            task_status: null,
            task_title: null,
            workflow_run_id: 'run-9',
            workflow_run_status: 'succeeded',
          },
        ],
      }),
    );
    vi.spyOn(api, 'getWorkflowRun').mockResolvedValue({
      id: 'run-9',
      status: 'succeeded',
    } as never);
    render(<TriggerDrawer target="workflow" scheduleId="sched-1" onClose={() => {}} />, { wrapper });

    expect(await screen.findByText('Past runs (1)')).toBeInTheDocument();
    expect(screen.getByText('nightly-quality', { selector: 'a' })).toHaveAttribute(
      'href',
      '/workflows/wf-1',
    );
    const chip = await screen.findByText('Succeeded');
    expect(chip.closest('a')?.getAttribute('href')).toBe('/workflow-runs/run-9');
  });
});
