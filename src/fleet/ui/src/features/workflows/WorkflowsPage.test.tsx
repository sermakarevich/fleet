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
import type { Workflow } from '../../shared/types';
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
});
