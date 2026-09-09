/**
 * Unit tests for the schedule list cells: next-run rendering, the
 * "never" and "skipped" last-run cases, and the disabled placeholder.
 * Renders scheduleColumns() through the shared DataList.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { formatShortDateTime } from '../../shared/format';
import type { Schedule } from '../../shared/types';
import { DataList } from '../../shared/ui/DataList';
import { scheduleColumns } from './scheduleColumns';

afterEach(cleanup);

// Minimal schedule; tests override what they need.
function makeSchedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    id: 'sched-1',
    name: 'nightly-triage',
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
    next_fire_at: '2026-09-10T09:00:00Z',
    run_count: 3,
    last_run: null,
    ...overrides,
  };
}

function renderList(schedule: Schedule) {
  render(
    <MemoryRouter>
      <DataList
        columns={scheduleColumns()}
        rows={[schedule]}
        rowKey={(s) => s.id}
        onRowClick={vi.fn()}
        empty="No schedules."
        isMobile={false}
      />
    </MemoryRouter>,
  );
}

describe('scheduleColumns', () => {
  it('renders the next run time when enabled', () => {
    const schedule = makeSchedule();
    renderList(schedule);
    expect(screen.getByText(formatShortDateTime(schedule.next_fire_at as string))).toBeInTheDocument();
  });

  it('renders "never" when there is no last run', () => {
    renderList(makeSchedule({ last_run: null }));
    expect(screen.getByText('never')).toBeInTheDocument();
  });

  it('renders "skipped" for a skipped last run', () => {
    renderList(
      makeSchedule({
        last_run: {
          schedule_id: 'sched-1',
          n: 3,
          scheduled_for: '2026-09-09T09:00:00Z',
          fired_at: '2026-09-09T09:00:01Z',
          trigger: 'cron',
          task_id: null,
          skipped: true,
          reason: 'previous task still open',
          task_status: null,
          task_title: null,
        },
      }),
    );
    expect(screen.getByText('skipped')).toBeInTheDocument();
  });

  it('renders a placeholder next run when disabled', () => {
    const schedule = makeSchedule({ enabled: false });
    renderList(schedule);
    expect(screen.queryByText(formatShortDateTime(schedule.next_fire_at as string))).not.toBeInTheDocument();
    expect(screen.getByText('off')).toBeInTheDocument();
  });

  it('renders the empty state when there are no schedules', () => {
    render(
      <MemoryRouter>
        <DataList
          columns={scheduleColumns()}
          rows={[]}
          rowKey={(s: Schedule) => s.id}
          empty="No schedules yet."
          isMobile={false}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('No schedules yet.')).toBeInTheDocument();
  });
});
