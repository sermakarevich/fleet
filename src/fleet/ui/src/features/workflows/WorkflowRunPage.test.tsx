/**
 * Page test for the run monitor detail: the stage grid renders one card
 * per step with a task link, Cancel is hidden for finished runs and
 * two-step for live ones.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { api } from '../../shared/api';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import type { Workflow, WorkflowRun, WorkflowStepRun } from '../../shared/types';
import { WorkflowRunPage } from './WorkflowRunPage';

afterEach(cleanup);

function step(overrides: Partial<WorkflowStepRun> = {}): WorkflowStepRun {
  return {
    step_name: 'lint',
    stage_index: 0,
    task_id: 't1',
    task_status: 'closed',
    state: 'done',
    task_title: 'Lint it',
    updated_at: '2026-09-09T09:01:00Z',
    ...overrides,
  };
}

function makeRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    id: 'run-1',
    workflow_id: 'wf-1',
    workflow_name: 'nightly-quality',
    n: 3,
    trigger: 'manual',
    schedule_id: null,
    status: 'running',
    reason: '',
    started_at: '2026-09-09T09:00:00Z',
    finished_at: null,
    steps: [
      step(),
      step({
        step_name: 'tests', stage_index: 1, task_id: 't2', task_status: 'in_progress',
        state: 'running', task_title: 'Run tests', updated_at: '2026-09-09T09:02:00Z',
      }),
    ],
    ...overrides,
  };
}

function makeWorkflow(): Workflow {
  return {
    id: 'wf-1',
    name: 'nightly-quality',
    description: '',
    defaults: { cwd: null, coder: null, model: null, priority: 2 },
    stages: [
      {
        name: 'checks',
        steps: [{ name: 'lint', title: 'Lint', description: '' }],
      },
      {
        name: 'report',
        steps: [{ name: 'tests', title: 'Run tests', description: '' }],
      },
    ],
    step_count: 2,
    stage_count: 2,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-09T10:00:00Z',
    run_count: 3,
    last_run: null,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/workflow-runs/run-1']}>
          <Routes>
            <Route path="/workflow-runs/:runId" element={children} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
  vi.spyOn(api, 'getWorkflow').mockResolvedValue(makeWorkflow());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WorkflowRunPage', () => {
  it('renders one stage-grid card per step with its task link', async () => {
    vi.spyOn(api, 'getWorkflowRun').mockResolvedValue(makeRun());
    render(<WorkflowRunPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByText('lint').length).toBeGreaterThan(0));
    expect(screen.getAllByText('tests').length).toBeGreaterThan(0);
    expect(screen.getByText('checks')).toBeInTheDocument();
    expect(screen.getByText('report')).toBeInTheDocument();
    const taskLink = screen.getByRole('link', { name: /Open task t1/ });
    expect(taskLink).toHaveAttribute('href', '/tasks/t1');
    expect(screen.getByText('Timeline')).toBeInTheDocument();
  });

  it('hides Cancel for a succeeded run', async () => {
    vi.spyOn(api, 'getWorkflowRun').mockResolvedValue(
      makeRun({ status: 'succeeded', finished_at: '2026-09-09T09:05:00Z' }),
    );
    render(<WorkflowRunPage />, { wrapper });
    await waitFor(() => expect(screen.getByText('Succeeded')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Cancel/ })).not.toBeInTheDocument();
  });

  it('asks for confirmation before cancelling a running run', async () => {
    vi.spyOn(api, 'getWorkflowRun').mockResolvedValue(makeRun());
    const cancelSpy = vi.spyOn(api, 'cancelWorkflowRun').mockResolvedValue(makeRun({ status: 'cancelled' }));
    render(<WorkflowRunPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByText('Running').length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole('button', { name: 'Cancel run' }));
    expect(screen.getByText('Cancel run?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument();
    expect(cancelSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(cancelSpy).toHaveBeenCalledWith('run-1'));
  });
});
