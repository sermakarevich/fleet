/**
 * Unit tests for the recurring schedules table: rows link to the workflow
 * definition and to the last workflow run, plus the empty state and the
 * "never"/"skipped" last-run cases.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { formatShortDateTime } from '../../shared/format';
import type { Schedule } from '../../shared/types';
import { RecurringTable } from './RecurringTable';

afterEach(cleanup);

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

// Minimal recurring schedule; tests override what they need.
function makeSchedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
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
    next_fire_at: '2026-09-10T09:00:00Z',
    run_count: 3,
    last_run: null,
    ...overrides,
  };
}

function lastRun(overrides = {}) {
  return {
    schedule_id: 'sched-1',
    n: 3,
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
    ...overrides,
  };
}

describe('RecurringTable', () => {
  it('rows link to the workflow and to the last run', () => {
    const schedule = makeSchedule({ last_run: lastRun() });
    render(
      <RecurringTable
        items={[schedule]}
        workflowNames={{ 'wf-1': 'nightly-quality' }}
        selectedId={null}
        onSelect={vi.fn()}
        isMobile={false}
      />,
      { wrapper },
    );
    const workflowLink = screen.getByText('nightly-quality', { selector: 'a' });
    expect(workflowLink.getAttribute('href')).toBe('/workflows/wf-1');
    const runChip = screen.getByText('Succeeded');
    const runLink = runChip.closest('a');
    expect(runLink?.getAttribute('href')).toBe('/workflow-runs/run-9');
  });

  it('renders the next run time when enabled', () => {
    const schedule = makeSchedule();
    render(
      <RecurringTable
        items={[schedule]}
        workflowNames={{}}
        selectedId={null}
        onSelect={vi.fn()}
        isMobile={false}
      />,
      { wrapper },
    );
    expect(
      screen.getByText(formatShortDateTime(schedule.next_fire_at as string)),
    ).toBeInTheDocument();
  });

  it('renders "never" when there is no last run', () => {
    render(
      <RecurringTable
        items={[makeSchedule({ last_run: null })]}
        workflowNames={{}}
        selectedId={null}
        onSelect={vi.fn()}
        isMobile={false}
      />,
      { wrapper },
    );
    expect(screen.getByText('never')).toBeInTheDocument();
  });

  it('renders "skipped" for a skipped last run', () => {
    const schedule = makeSchedule({ last_run: lastRun({ skipped: true, workflow_run_id: null }) });
    render(
      <RecurringTable
        items={[schedule]}
        workflowNames={{}}
        selectedId={null}
        onSelect={vi.fn()}
        isMobile={false}
      />,
      { wrapper },
    );
    expect(screen.getByText('skipped')).toBeInTheDocument();
  });

  it('renders the empty state when there are no recurring workflows', () => {
    render(
      <RecurringTable
        items={[]}
        workflowNames={{}}
        selectedId={null}
        onSelect={vi.fn()}
        isMobile={false}
      />,
      { wrapper },
    );
    expect(screen.getByText(/No recurring workflows/)).toBeInTheDocument();
  });
});
