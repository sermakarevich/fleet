/**
 * Unit tests for the runs list: row rendering, progress counts, the
 * mobile card variant, and the status filter in the Runs view.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../../shared/api';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import type { WorkflowRun, WorkflowStepRun } from '../../shared/types';
import { RunsTable } from './RunsTable';
import { WorkflowsPage } from './WorkflowsPage';

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

// Minimal run; tests override what they need.
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
        step_name: 'tests', task_id: 't2', task_status: 'in_progress',
        state: 'running', task_title: 'Run tests', updated_at: '2026-09-09T09:02:00Z',
      }),
      step({
        step_name: 'docs', task_id: 't3', task_status: 'open',
        state: 'waiting', task_title: null, updated_at: '2026-09-09T09:00:30Z',
      }),
    ],
    ...overrides,
  };
}

function tableWrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

function pageWrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/workflows?view=runs']}>{children}</MemoryRouter>
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
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RunsTable', () => {
  it('renders one row per run with workflow, number, trigger and status', () => {
    const onOpen = vi.fn();
    render(
      <RunsTable
        runs={[makeRun(), makeRun({ id: 'run-2', n: 4, trigger: 'cron', status: 'succeeded' })]}
        onOpen={onOpen}
        isMobile={false}
      />,
      { wrapper: tableWrapper },
    );
    expect(screen.getAllByText('nightly-quality')).toHaveLength(2);
    expect(screen.getByText('#3')).toBeInTheDocument();
    expect(screen.getByText('#4')).toBeInTheDocument();
    expect(screen.getByText('manual')).toBeInTheDocument();
    expect(screen.getByText('cron')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('Succeeded')).toBeInTheDocument();
  });

  it('shows done/total progress counts', () => {
    render(<RunsTable runs={[makeRun()]} onOpen={vi.fn()} isMobile={false} />, {
      wrapper: tableWrapper,
    });
    expect(screen.getByText('1/3')).toBeInTheDocument();
    expect(screen.getByLabelText('1 of 3 steps done')).toBeInTheDocument();
  });

  it('renders the mobile card variant', () => {
    render(<RunsTable runs={[makeRun()]} onOpen={vi.fn()} isMobile={true} />, {
      wrapper: tableWrapper,
    });
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('1/3')).toBeInTheDocument();
  });

  it('renders the empty state when there are no runs', () => {
    render(<RunsTable runs={[]} onOpen={vi.fn()} isMobile={false} />, {
      wrapper: tableWrapper,
    });
    expect(screen.getByText(/No runs yet/)).toBeInTheDocument();
  });

  it('filters by status in the Runs view', async () => {
    vi.spyOn(api, 'listWorkflows').mockResolvedValue([]);
    const listSpy = vi.spyOn(api, 'listAllWorkflowRuns').mockResolvedValue({ runs: [], total: 0 });
    render(<WorkflowsPage />, { wrapper: pageWrapper });
    await waitFor(() => expect(screen.getByText(/No runs yet/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Running' }));
    await waitFor(() =>
      expect(listSpy).toHaveBeenCalledWith({ status: 'running', limit: 50, offset: 0 }),
    );
  });
});
