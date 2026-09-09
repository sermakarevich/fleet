/**
 * Page test for the workflows tab: the Import YAML button posts the
 * uploaded file text to the import endpoint.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../../shared/api';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import type { Schedule, Workflow } from '../../shared/types';
import { WorkflowsPage } from './WorkflowsPage';

afterEach(cleanup);

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/workflows']}>{children}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function scheduledWrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/workflows?tab=scheduled']}>{children}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

const YAML_TEXT = 'fleet_workflow: 1\nname: nightly-quality\nstages: []\n';

function makeWorkflow(): Workflow {
  return {
    id: 'wf-9',
    name: 'nightly-quality',
    description: '',
    defaults: { cwd: null, coder: null, model: null, priority: 2 },
    stages: [],
    step_count: 0,
    stage_count: 0,
    created_at: '2026-09-09T10:00:00Z',
    updated_at: '2026-09-09T10:00:00Z',
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
  vi.spyOn(api, 'listWorkflows').mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WorkflowsPage', () => {
  it('import button posts the file text', async () => {
    const importSpy = vi.spyOn(api, 'importWorkflow').mockResolvedValue(makeWorkflow());
    render(<WorkflowsPage />, { wrapper });
    await waitFor(() => expect(screen.getByText(/No workflows yet/)).toBeInTheDocument());

    const input = screen.getByLabelText('Import workflow YAML file');
    const file = new File([YAML_TEXT], 'nightly.yaml', { type: 'text/yaml' });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(importSpy).toHaveBeenCalledWith(YAML_TEXT, undefined));
  });

  it('Scheduled sub-tab lists workflow-target schedules with the Overlap column', async () => {    const listSpy = vi.spyOn(api, 'getSchedules').mockResolvedValue([
      {
        id: 'sched-w1',
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
        overlap: 'queue',
        target: 'workflow',
        workflow_id: 'wf-9',
        created_at: '2026-09-09T10:00:00Z',
        updated_at: '2026-09-09T10:00:00Z',
        next_fire_at: null,
        run_count: 0,
        last_run: null,
      } as Schedule,
    ]);
    render(<WorkflowsPage />, { wrapper: scheduledWrapper });

    expect(await screen.findByText('nightly-quality')).toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledWith('workflow');
    expect(screen.getByText('Overlap')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Scheduled' })).toHaveAttribute('aria-selected', 'true');
  });

  it('Run opens the input form when the workflow declares inputs', async () => {
    const withInputs: Workflow = {
      ...makeWorkflow(),
      id: 'wf-inputs',
      name: 'paper-summary',
      inputs: [
        { name: 'url', description: 'Link to the source.', required: true, default: null },
      ],
    };
    vi.mocked(api.listWorkflows).mockResolvedValue([withInputs]);
    render(<WorkflowsPage />, { wrapper });
    await waitFor(() => expect(screen.getByText('paper-summary')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    // The run form opens instead of running immediately.
    expect(await screen.findByText('Run paper-summary')).toBeInTheDocument();
    expect(screen.getByLabelText('url (required)')).toBeInTheDocument();
  });

  it('Run starts immediately when the workflow declares no inputs', async () => {
    const plain = makeWorkflow();
    vi.mocked(api.listWorkflows).mockResolvedValue([plain]);
    const runSpy = vi.spyOn(api, 'runWorkflow').mockResolvedValue({
      run: {
        id: 'run-1', workflow_id: plain.id, workflow_name: plain.name, n: 1,
        trigger: 'manual', schedule_id: null, status: 'running', reason: '',
        started_at: '2026-09-09T10:00:00Z', finished_at: null, inputs: {}, steps: [],
      },
    });
    render(<WorkflowsPage />, { wrapper });
    await waitFor(() => expect(screen.getByText('nightly-quality')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await waitFor(() => expect(runSpy).toHaveBeenCalledWith('wf-9', undefined));
    expect(screen.queryByLabelText('url (required)')).not.toBeInTheDocument();
  });
});
