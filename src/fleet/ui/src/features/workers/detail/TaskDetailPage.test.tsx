/**
 * Tests for the worker detail page (ADR 0017 U2): the four-tab shell
 * (Activity, Attempts, Result, Bead), the Bead tab hiding when the bead
 * query fails, and Close / Reopen / remove-assignee firing the right
 * hooks through Confirm.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ToastProvider } from '../../../shared/contexts/ToastContext';
import { api, ApiError } from '../../../shared/api';
import type { BeadDetail, RuntimeConfig, TaskDetail } from '../../../shared/types';
import { TaskDetailPage } from './TaskDetailPage';

afterEach(cleanup);

beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function makeTask(partial?: Partial<TaskDetail>): TaskDetail {
  return {
    id: 'w1',
    title: 'worker one',
    description: 'does things',
    status: 'blocked',
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
    blocked_reason: 'waiting on dep',
    blocked_at: '2026-09-09T11:00:00Z',
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
    attempts: [],
    ...partial,
  } as TaskDetail;
}

function makeBead(partial?: Partial<BeadDetail>): BeadDetail {
  return {
    id: 'w1',
    title: 'worker one',
    status: 'blocked',
    priority: 2,
    issue_type: 'bug',
    assignee: 'coder-a',
    description: 'does things',
    notes: 'blocked on dep-1',
    created_at: '2026-09-09T10:00:00Z',
    updated_at: '2026-09-09T11:00:00Z',
    closed_at: null,
    close_reason: null,
    dependencies: [
      { id: 'dep-1', title: 'Dep one', status: 'open', dependency_type: 'blocks' },
      { id: 'dep-2', title: 'Dep two', status: 'closed', dependency_type: null },
    ],
    comments: [
      { id: 1, author: 'alice', text: 'first comment', created_at: '2026-09-09T10:30:00Z' },
    ],
    ...partial,
  } as BeadDetail;
}

function mockAll(task: TaskDetail, bead: BeadDetail) {
  vi.spyOn(api, 'getTask').mockResolvedValue(task);
  vi.spyOn(api, 'getBead').mockResolvedValue(bead);
  vi.spyOn(api, 'getConfig').mockResolvedValue({} as RuntimeConfig);
  vi.spyOn(api, 'getActivity').mockResolvedValue({
    items: [],
    total: 0,
    has_earlier: false,
    latest_attempt: 1,
    stderr: null,
  });
  vi.spyOn(api, 'getTaskChildren').mockResolvedValue({ children: [], children_md: null });
  vi.spyOn(api, 'getArtifactBundle').mockResolvedValue({
    result: null,
    state: null,
    outputs: [],
    docs: [],
    files: [],
    worktree: null,
  });
}

function wrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter initialEntries={['/workers/w1']}>
            <Routes>
              <Route path="/workers/:id" element={children} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  };
}

async function openTab(name: string) {
  fireEvent.click(screen.getByRole('tab', { name }));
}

describe('TaskDetailPage tabs (ADR 0017)', () => {
  it('shows the four tabs and selects Activity by default', async () => {
    mockAll(makeTask(), makeBead());
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    for (const name of ['Activity', 'Attempts', 'Result', 'Bead']) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument();
    }
    for (const name of ['Live', 'Events', 'Log', 'Stderr']) {
      expect(screen.queryByRole('tab', { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { name: 'Activity' })).toHaveAttribute('aria-selected', 'true');
    // Empty finished feed on the default tab.
    expect(await screen.findByText('No activity recorded.')).toBeInTheDocument();
  });

  it('hides the Bead tab when the bead query fails', async () => {
    vi.spyOn(api, 'getTask').mockResolvedValue(makeTask());
    vi.spyOn(api, 'getBead').mockRejectedValue(new ApiError(404, 'bead w1 not found'));
    vi.spyOn(api, 'getConfig').mockResolvedValue({} as RuntimeConfig);
    vi.spyOn(api, 'getActivity').mockResolvedValue({
      items: [],
      total: 0,
      has_earlier: false,
      latest_attempt: 1,
      stderr: null,
    });
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    expect(screen.getByRole('tab', { name: 'Activity' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Bead' })).not.toBeInTheDocument();
  });

  it('shows priority and issue-type pills from the bead payload', async () => {
    mockAll(makeTask(), makeBead());
    render(<TaskDetailPage />, { wrapper: wrapper() });

    expect(await screen.findByText('worker one')).toBeInTheDocument();
    expect(screen.getByText('priority 2')).toBeInTheDocument();
    expect(screen.getByText('bug')).toBeInTheDocument();
    expect(screen.getByText('assignee: coder-a')).toBeInTheDocument();
  });

  it('Bead tab shows dependencies, comments and the raw payload with a copy button', async () => {
    mockAll(makeTask(), makeBead());
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    await openTab('Bead');
    expect(await screen.findByRole('heading', { name: 'Dependencies' })).toBeInTheDocument();
    const depLinks = screen.getAllByRole('link', { name: 'dep-1' });
    expect(depLinks[0].getAttribute('href')).toBe('/workers/dep-1');
    expect(screen.getByText('blocked on dep-1')).toBeInTheDocument();
    expect(screen.getByText('first comment')).toBeInTheDocument();
    const pre = screen.getByText(/"issue_type": "bug"/);
    expect(pre.tagName).toBe('PRE');
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });

  it('Result tab renders the bundle', async () => {
    mockAll(makeTask({ status: 'done' }), makeBead());
    vi.mocked(api.getArtifactBundle).mockResolvedValue({
      result: {
        name: 'RESULT.json',
        content: JSON.stringify({ status: 'done', summary: 'bundle summary' }),
        mtime: 0,
        truncated: false,
      },
      state: null,
      outputs: [{ name: 'out.txt', path: '/tmp/w1/outputs/out.txt', size: 10 }],
      docs: [],
      files: [],
      worktree: null,
    });
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    await openTab('Result');
    expect(await screen.findByRole('heading', { name: 'Result' })).toBeInTheDocument();
    expect(screen.getByText('bundle summary')).toBeInTheDocument();
    expect(screen.getByText('out.txt')).toBeInTheDocument();
  });

  it('Close confirms through Confirm and calls closeTask', async () => {
    mockAll(makeTask(), makeBead());
    const closeSpy = vi.spyOn(api, 'closeTask').mockResolvedValue(undefined);
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.getByText('Close?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(closeSpy).toHaveBeenCalledWith('w1'));
  });

  it('Remove assignee confirms through Confirm and calls removeAssignee', async () => {
    mockAll(makeTask(), makeBead());
    const removeSpy = vi.spyOn(api, 'removeAssignee').mockResolvedValue(undefined);
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    fireEvent.click(screen.getByRole('button', { name: 'Remove assignee' }));
    expect(screen.getByText('Remove assignee?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith('w1'));
  });

  it('shows "Task not found." on a 404', async () => {
    vi.spyOn(api, 'getTask').mockRejectedValue(new ApiError(404, 'task w9 not found'));
    vi.spyOn(api, 'getBead').mockRejectedValue(new ApiError(404, 'bead w9 not found'));
    vi.spyOn(api, 'getConfig').mockResolvedValue({} as RuntimeConfig);
    render(<TaskDetailPage />, { wrapper: wrapper() });
    expect(await screen.findByText('Task not found.')).toBeInTheDocument();
  });

  it('shows the load error for non-404 failures', async () => {
    vi.spyOn(api, 'getTask').mockRejectedValue(new Error('db down'));
    vi.spyOn(api, 'getBead').mockRejectedValue(new Error('db down'));
    vi.spyOn(api, 'getConfig').mockResolvedValue({} as RuntimeConfig);
    render(<TaskDetailPage />, { wrapper: wrapper() });
    expect(await screen.findByText('Could not load task: db down')).toBeInTheDocument();
  });
});

describe('TaskDetailPage closed bead', () => {
  it('Reopen confirms through Confirm and calls setBeadStatus open', async () => {
    mockAll(makeTask({ status: 'closed' }), makeBead({ status: 'closed' }));
    const statusSpy = vi.spyOn(api, 'setBeadStatus').mockResolvedValue({ ok: true });
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reopen' }));
    expect(screen.getByText('Reopen?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(statusSpy).toHaveBeenCalledWith('w1', 'open'));
  });
});
