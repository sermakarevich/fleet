/**
 * Tests for the worker detail page bead absorption (ADR 0009): header
 * priority/issue-type pills from the bead payload, the Dependencies /
 * Comments / Bead tabs, and Close / Reopen / remove-assignee firing the
 * right hooks through Confirm.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ToastProvider } from '../../../shared/contexts/ToastContext';
import { api } from '../../../shared/api';
import type { BeadDetail, RuntimeConfig, TaskDetail } from '../../../shared/types';
import { TaskDetailPage } from './TaskDetailPage';

afterEach(cleanup);

class QuietSocket {
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent<string>) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly url: string) {}
  close(): void {}
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', QuietSocket);
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

describe('TaskDetailPage bead absorption', () => {
  it('shows priority and issue-type pills from the bead payload', async () => {
    mockAll(makeTask(), makeBead());
    render(<TaskDetailPage />, { wrapper: wrapper() });

    expect(await screen.findByText('worker one')).toBeInTheDocument();
    expect(screen.getByText('priority 2')).toBeInTheDocument();
    expect(screen.getByText('bug')).toBeInTheDocument();
    expect(screen.getByText('assignee: coder-a')).toBeInTheDocument();
  });

  it('Dependencies tab lists type, status, worker links and flags incomplete deps', async () => {
    mockAll(makeTask(), makeBead());
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    await openTab('Dependencies');
    // "Why blocked" section reused from the old bead drawer.
    expect(screen.getByText('Why blocked')).toBeInTheDocument();
    expect(screen.getByText('blocked on dep-1')).toBeInTheDocument();
    // Full list with type + status + links (the open dep also shows in
    // the Why-blocked section, so it renders twice).
    expect(screen.getAllByText('Dep one')).toHaveLength(2);
    expect(screen.getAllByText('blocks')).toHaveLength(2);
    const links = screen.getAllByRole('link', { name: 'dep-1' });
    expect(links[0]).toHaveAttribute('href', '/workers/dep-1');
    expect(screen.getByText('waiting')).toBeInTheDocument();
  });

  it('Comments tab lists the bead thread', async () => {
    mockAll(makeTask(), makeBead());
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    await openTab('Comments');
    expect(screen.getByText('first comment')).toBeInTheDocument();
    expect(screen.getByText('alice')).toBeInTheDocument();
  });

  it('Bead tab pretty-prints the raw payload with a copy button', async () => {
    mockAll(makeTask(), makeBead());
    render(<TaskDetailPage />, { wrapper: wrapper() });
    await screen.findByText('worker one');

    await openTab('Bead');
    const pre = screen.getByText(/"issue_type": "bug"/);
    expect(pre.tagName).toBe('PRE');
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
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
