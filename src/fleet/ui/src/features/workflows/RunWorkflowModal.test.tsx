/**
 * Page test for the run form modal: one field per declared input with
 * defaults pre-filled, Run gated on required inputs, submit posts the
 * values, and a 422 from the server shows inline.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { api, ApiError } from '../../shared/api';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import type { Workflow, WorkflowRun } from '../../shared/types';
import { RunWorkflowModal } from './RunWorkflowModal';

afterEach(cleanup);

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
    name: 'paper-summary',
    description: 'Summarise a paper',
    defaults: { cwd: null, coder: null, model: null, priority: 2, isolation: null },
    inputs: [
      { name: 'url', description: 'Link to the source to summarise.', required: true, default: null },
      { name: 'channel', description: 'Where to post.', required: false, default: '#ai-papers' },
    ],
    stages: [],
    step_count: 0,
    stage_count: 0,
    created_at: '2026-09-09T10:00:00Z',
    updated_at: '2026-09-09T10:00:00Z',
    run_count: 0,
    last_run: null,
  };
}

function makeRun(): WorkflowRun {
  return {
    id: 'run-9',
    workflow_id: 'wf-1',
    workflow_name: 'paper-summary',
    n: 1,
    trigger: 'manual',
    schedule_id: null,
    status: 'running',
    reason: '',
    started_at: '2026-09-09T10:00:00Z',
    finished_at: null,
    inputs: { url: 'https://example.com/p' },
    steps: [],
  };
}

beforeEach(() => {
  vi.spyOn(api, 'getCoders').mockResolvedValue({ coders: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RunWorkflowModal', () => {
  it('renders one field per input with the default pre-filled', () => {
    render(<RunWorkflowModal workflow={makeWorkflow()} onClose={() => undefined} />, { wrapper });
    expect(screen.getByText('Run paper-summary')).toBeInTheDocument();
    expect(screen.getByText('Link to the source to summarise.')).toBeInTheDocument();
    // Required marker on url, default pre-filled on channel.
    expect(screen.getByLabelText('url (required)')).toHaveValue('');
    expect(screen.getByLabelText('channel')).toHaveValue('#ai-papers');
  });

  it('disables Run until required inputs are filled, then posts the values', async () => {
    const runSpy = vi.spyOn(api, 'runWorkflow').mockResolvedValue({ run: makeRun() });
    const onClose = vi.fn();
    const onStarted = vi.fn();
    render(<RunWorkflowModal workflow={makeWorkflow()} onClose={onClose} onStarted={onStarted} />, { wrapper });

    const runBtn = screen.getByRole('button', { name: 'Run' });
    expect(runBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText('url (required)'), {
      target: { value: 'https://example.com/paper' },
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await waitFor(() =>
      expect(runSpy).toHaveBeenCalledWith('wf-1', {
        url: 'https://example.com/paper',
        channel: '#ai-papers',
      }),
    );
    expect(onStarted).toHaveBeenCalledWith('run-9');
    expect(onClose).toHaveBeenCalled();
  });

  it('shows a server 422 message inline', async () => {
    vi.spyOn(api, 'runWorkflow').mockRejectedValue(
      new ApiError(422, 'inputs: unknown input "bogus"'),
    );
    render(<RunWorkflowModal workflow={makeWorkflow()} onClose={() => undefined} />, { wrapper });

    fireEvent.change(screen.getByLabelText('url (required)'), {
      target: { value: 'https://example.com/paper' },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Run' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('inputs: unknown input "bogus"');
  });
});
