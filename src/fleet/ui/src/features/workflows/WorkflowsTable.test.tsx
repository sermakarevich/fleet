/**
 * Unit tests for the workflow list: row rendering and the empty state.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { Workflow } from '../../shared/types';
import { WorkflowsTable } from './WorkflowsTable';

afterEach(cleanup);

function tableWrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

// Minimal workflow; tests override what they need.
function makeWorkflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: 'wf-1',
    name: 'nightly-quality',
    description: '',
    defaults: { cwd: null, coder: null, model: null, priority: 2 },
    stages: [
      { name: 'checks', steps: [{ name: 'lint', title: 'Lint', description: '' }] },
      { name: 'report', steps: [{ name: 'summary', title: 'Summarise', description: '' }] },
    ],
    step_count: 2,
    stage_count: 2,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-09T10:00:00Z',
    run_count: 4,
    last_run: null,
    ...overrides,
  };
}

const handlers = {
  onEdit: vi.fn(),
  onRun: vi.fn(),
  onDelete: vi.fn(),
};

describe('WorkflowsTable', () => {
  it('renders one row per workflow with its shape', () => {
    render(
      <WorkflowsTable
        items={[makeWorkflow(), makeWorkflow({ id: 'wf-2', name: 'release' })]}
        runningId={null}
        isMobile={false}
        {...handlers}
      />,
      { wrapper: tableWrapper },
    );
    expect(screen.getByText('nightly-quality')).toBeInTheDocument();
    expect(screen.getByText('release')).toBeInTheDocument();
    expect(screen.getAllByText('2 stages · 2 steps')).toHaveLength(2);
  });

  it('renders the empty state when there are no workflows', () => {
    render(<WorkflowsTable items={[]} runningId={null} isMobile={false} {...handlers} />, {
      wrapper: tableWrapper,
    });
    expect(screen.getByText(/No workflows yet/)).toBeInTheDocument();
  });

  it('shows the last run status when present', () => {
    render(
      <WorkflowsTable
        items={[
          makeWorkflow({
            last_run: {
              id: 'run-1',
              workflow_id: 'wf-1',
              workflow_name: 'nightly-quality',
              n: 4,
              trigger: 'manual',
              schedule_id: null,
              status: 'succeeded',
              reason: '',
              started_at: '2026-09-09T09:00:00Z',
              finished_at: '2026-09-09T09:05:00Z',
              steps: [],
            },
          }),
        ]}
        runningId={null}
        isMobile={false}
        {...handlers}
      />,
      { wrapper: tableWrapper },
    );
    expect(screen.getByText('Succeeded')).toBeInTheDocument();
  });
});
