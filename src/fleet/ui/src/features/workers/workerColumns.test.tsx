/**
 * Tests for the stale-lease badge: staleness trusts the server's
 * lease.alive flag (GET /api/tasks), never the client clock, which goes
 * stale whenever the list is fed by socket overlays.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { TaskSummary } from '../../shared/types';
import { isStaleLease, taskColumns, TaskTitleCell, type TaskListCallbacks } from './workerColumns';

afterEach(cleanup);

function makeTask(partial: Partial<TaskSummary> & { id: string }): TaskSummary {
  return {
    title: `title-${partial.id}`,
    description: null,
    status: 'in_progress',
    cwd: null,
    coder: null,
    model: null,
    priority: null,
    depends_on: [],
    created_at: '2026-09-09T10:00:00Z',
    started_at: '2026-09-09T10:00:00Z',
    ended_at: null,
    elapsed_sec: null,
    idle_sec: null,
    events: 0,
    context_tokens: null,
    context_pct: null,
    context_limit: null,
    last_event_kind: null,
    last_event_detail: null,
    blocked_reason: null,
    blocked_at: null,
    ignore_until: null,
    ignored: false,
    rounds: { failure: 0, stall: 0, context: 0, partial: 0, noclose: 0 },
    restarts: 0,
    context_rounds: 0,
    compactions: 0,
    peak_context_pct: null,
    last_outcome: null,
    last_outcome_reason: null,
    last_action: null,
    result: null,
    state_excerpt: null,
    worker: null,
    job_phase: null,
    job_artifacts: { research: false, design: false, tasks: false, approved: false },
    steps: [],
    lease: null,
    has_task_dir: true,
    ...partial,
  } as TaskSummary;
}

const OLD_LEASE = {
  // Far in the past: must NOT trigger the badge while alive is true.
  heartbeat_at: '2020-01-01T00:00:00Z',
  lease_until: '2020-01-01T00:01:30Z',
  alive: true,
};

describe('isStaleLease', () => {
  it('is true only for running tasks with lease.alive === false', () => {
    expect(
      isStaleLease(
        makeTask({ id: 'a', lease: { ...OLD_LEASE, alive: false } }),
      ),
    ).toBe(true);
  });

  it('is false when alive is true even if lease_until is in the past', () => {
    expect(isStaleLease(makeTask({ id: 'b', lease: { ...OLD_LEASE } }))).toBe(false);
  });

  it('is false when the task is not running', () => {
    expect(
      isStaleLease(
        makeTask({ id: 'c', status: 'failed', lease: { ...OLD_LEASE, alive: false } }),
      ),
    ).toBe(false);
  });

  it('is false when there is no lease', () => {
    expect(isStaleLease(makeTask({ id: 'd', lease: null }))).toBe(false);
  });
});

describe('TaskTitleCell stale-lease badge', () => {
  it('renders the badge with heartbeat/lease tooltip when alive is false', () => {
    render(
      <TaskTitleCell
        task={makeTask({
          id: 'e',
          lease: { heartbeat_at: '2026-09-09T10:00:00Z', lease_until: '2026-09-09T10:01:30Z', alive: false },
        })}
      />,
    );
    const badge = screen.getByText('stale lease');
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute('title')).toContain('2026-09-09T10:00:00Z');
    expect(badge.getAttribute('title')).toContain('2026-09-09T10:01:30Z');
  });

  it('does not render the badge when alive is true, even with an expired lease_until', () => {
    render(<TaskTitleCell task={makeTask({ id: 'f', lease: { ...OLD_LEASE } })} />);
    expect(screen.queryByText('stale lease')).not.toBeInTheDocument();
  });
});

const TEST_CB: TaskListCallbacks = {
  confirming: null,
  stoppingIds: new Set<string>(),
  onActionClick: () => {},
  onActionConfirm: () => {},
  onActionCancel: () => {},
};

function coderCell(task: TaskSummary) {
  const col = taskColumns(TEST_CB).find((c) => c.key === 'coder');
  if (!col) throw new Error('coder column missing');
  return col.render(task);
}

describe('coder cell', () => {
  it('renders coder and provider-stripped model on separate lines with full string as title', () => {
    const { container } = render(
      <>{coderCell(makeTask({ id: 'g', coder: 'opencode', model: 'opencode-go/muse-spark-1.3-contributor' }))}</>,
    );
    expect(screen.getByText('opencode')).toBeInTheDocument();
    expect(screen.getByText('muse-spark-1.3-contributor')).toBeInTheDocument();
    expect(screen.queryByText('opencode-go/muse-spark-1.3-contributor')).not.toBeInTheDocument();
    const wrapper = container.querySelector('[title]');
    expect(wrapper?.getAttribute('title')).toBe('opencode · opencode-go/muse-spark-1.3-contributor');
  });

  it('renders (default) when coder and model are null', () => {
    render(<>{coderCell(makeTask({ id: 'h', coder: null, model: null }))}</>);
    expect(screen.getByText('(default)')).toBeInTheDocument();
  });
});
