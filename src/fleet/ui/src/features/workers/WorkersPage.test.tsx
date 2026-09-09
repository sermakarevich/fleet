/**
 * Tests for the workers page: Runs/Scheduled sub-tabs, legacy route
 * redirects, strip counts, retry/close row actions on the right statuses
 * and status-filter URL round-trips.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router-dom';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import type { AnalyticsSummary, ChatQuestion, Schedule, TaskSummary } from '../../shared/types';
import { WorkersPage } from './WorkersPage';
import { TaskIdRedirect, ScheduleIdRedirect } from '../../app/App';

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
    ...partial,
  } as TaskSummary;
}

function makeSchedule(partial: Partial<Schedule> & { id: string }): Schedule {
  return {
    name: `sched-${partial.id}`,
    cron: '0 9 * * *',
    timezone: 'UTC',
    enabled: true,
    title: 'scheduled worker',
    description: '',
    cwd: null,
    coder: null,
    model: null,
    priority: 2,
    overlap: 'skip',
    target: 'task',
    workflow_id: null,
    created_at: '2026-09-09T09:00:00Z',
    updated_at: '2026-09-09T09:00:00Z',
    next_fire_at: null,
    run_count: 0,
    last_run: null,
    ...partial,
  } as Schedule;
}

function mockSummary(): AnalyticsSummary {
  return {
    window_days: 1,
    kpis: { rate_limited_tasks: null },
    errors_recent: [
      { id: 'f1', title: 'fail one', coder: null, model: null, outcome: 'failed', ended_at: '' },
      { id: 'f2', title: 'fail two', coder: null, model: null, outcome: 'failed', ended_at: '' },
    ],
    rate_limits: [
      { task_id: 'f1', ts: '2026-09-09T10:00:00Z' },
      { task_id: 'f1', ts: '2026-09-09T11:00:00Z' },
      { task_id: 'f2', ts: '2026-09-09T12:00:00Z' },
    ],
  } as unknown as AnalyticsSummary;
}

function mockQuestions(n: number): { now: number; pending: ChatQuestion[] } {
  return {
    now: Date.now(),
    pending: Array.from({ length: n }, (_, i) => ({ id: `q${i}`, status: 'pending' })),
  } as unknown as { now: number; pending: ChatQuestion[] };
}

function mockCommon(opts?: { tasks?: TaskSummary[]; schedules?: Schedule[]; questions?: number }) {
  vi.spyOn(api, 'getTasks').mockResolvedValue(opts?.tasks ?? []);
  vi.spyOn(api, 'getSchedules').mockResolvedValue(opts?.schedules ?? []);
  vi.spyOn(api, 'listWorkflows').mockResolvedValue([]);
  vi.spyOn(api, 'getAnalyticsSummary').mockResolvedValue(mockSummary());
  vi.spyOn(api, 'getChatQuestions').mockResolvedValue(mockQuestions(opts?.questions ?? 0));
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

function wrapper(initialEntries: string[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter initialEntries={initialEntries}>
            <Routes>
              <Route path="/workers" element={children} />
              <Route path="/inbox" element={<div>inbox marker</div>} />
            </Routes>
            <LocationProbe />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  };
}

describe('WorkersPage Runs tab', () => {
  it('renders the workers heading with Runs/Scheduled sub-tabs and the default running filter', async () => {
    mockCommon({ tasks: [makeTask({ id: 'w1', status: 'in_progress' }), makeTask({ id: 'w2', status: 'failed' })] });
    render(<WorkersPage />, { wrapper: wrapper(['/workers']) });

    expect(await screen.findByRole('heading', { name: /workers/ })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Runs' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Scheduled' })).toHaveAttribute('aria-selected', 'false');
    // Default filter is running: only the in-progress worker shows.
    expect(await screen.findByText('title-w1')).toBeInTheDocument();
    expect(screen.queryByText('title-w2')).not.toBeInTheDocument();
  });

  it('round-trips the status filter through the URL', async () => {
    mockCommon({
      tasks: [
        makeTask({ id: 'w1', status: 'failed' }),
        makeTask({ id: 'w2', status: 'blocked' }),
      ],
    });
    render(<WorkersPage />, { wrapper: wrapper(['/workers?status=failed']) });

    expect(await screen.findByText('title-w1')).toBeInTheDocument();
    expect(screen.queryByText('title-w2')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Blocked/ }));
    expect(await screen.findByText('title-w2')).toBeInTheDocument();
    expect(screen.queryByText('title-w1')).not.toBeInTheDocument();
    expect(screen.getByTestId('location').textContent).toContain('status=blocked');
  });
});

describe('WorkersPage Scheduled tab', () => {
  it('renders task-target schedules inside the sub-tab', async () => {
    mockCommon({
      tasks: [makeTask({ id: 'w1', status: 'in_progress' })],
      schedules: [makeSchedule({ id: 's1' })],
    });
    const listSpy = vi.spyOn(api, 'getSchedules');
    render(<WorkersPage />, { wrapper: wrapper(['/workers?tab=scheduled']) });

    expect(screen.getByRole('tab', { name: 'Scheduled' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('sched-s1')).toBeInTheDocument();
    expect(screen.queryByText('title-w1')).not.toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledWith('task');
  });
});

describe('NeedsAttentionStrip', () => {
  it('shows blocked, failed-24h, rate-limited-24h and question counts', async () => {
    mockCommon({ tasks: [makeTask({ id: 'w1', status: 'blocked' })], questions: 2 });
    render(<WorkersPage />, { wrapper: wrapper(['/workers?status=blocked']) });
    await screen.findByText('title-w1');

    expect(screen.getByRole('button', { name: 'blocked: 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'failed 24h: 2' })).toBeInTheDocument();
    expect(screen.getByTitle('Rate-limit events in the last 24 hours')).toHaveTextContent('3');
    expect(screen.getByRole('button', { name: 'pending questions: 2' })).toBeInTheDocument();
  });

  it('blocked tile filters the list, questions tile opens inbox', async () => {
    mockCommon({
      tasks: [
        makeTask({ id: 'w1', status: 'in_progress' }),
        makeTask({ id: 'w2', status: 'blocked' }),
      ],
      questions: 1,
    });
    render(<WorkersPage />, { wrapper: wrapper(['/workers']) });
    expect(await screen.findByText('title-w1')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'blocked: 1' }));
    expect(await screen.findByText('title-w2')).toBeInTheDocument();
    expect(screen.getByTestId('location').textContent).toContain('status=blocked');

    fireEvent.click(screen.getByRole('button', { name: 'pending questions: 1' }));
    expect(await screen.findByText('inbox marker')).toBeInTheDocument();
  });
});

describe('Retry and Close row actions', () => {
  it('shows Retry (not Close) on failed rows and confirms through the shared Confirm', async () => {
    mockCommon({ tasks: [makeTask({ id: 'w1', status: 'failed' })] });
    const requeueSpy = vi.spyOn(api, 'requeueTask').mockResolvedValue(undefined);
    render(<WorkersPage />, { wrapper: wrapper(['/workers?status=failed']) });

    const row = await screen.findByText('title-w1');
    const container = row.closest('tr') ?? row.closest('div');
    expect(container).toBeInTheDocument();
    const scope = within(container as HTMLElement);
    expect(scope.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(scope.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();

    fireEvent.click(scope.getByRole('button', { name: 'Retry' }));
    expect(scope.getByText('Retry?')).toBeInTheDocument();
    fireEvent.click(scope.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(requeueSpy).toHaveBeenCalledWith('w1'));
  });

  it('shows Close (not Retry) on running rows', async () => {
    mockCommon({ tasks: [makeTask({ id: 'w1', status: 'in_progress' })] });
    const closeSpy = vi.spyOn(api, 'closeTask').mockResolvedValue(undefined);
    render(<WorkersPage />, { wrapper: wrapper(['/workers']) });

    const row = await screen.findByText('title-w1');
    const container = row.closest('tr') ?? row.closest('div');
    const scope = within(container as HTMLElement);
    expect(scope.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(scope.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();

    fireEvent.click(scope.getByRole('button', { name: 'Close' }));
    expect(scope.getByText('Close?')).toBeInTheDocument();
    fireEvent.click(scope.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(closeSpy).toHaveBeenCalledWith('w1'));
  });

  it('shows Retry on blocked rows and Close on queued rows', async () => {
    mockCommon({
      tasks: [
        makeTask({ id: 'w1', status: 'blocked' }),
        makeTask({ id: 'w2', status: 'open' }),
      ],
    });
    render(<WorkersPage />, { wrapper: wrapper(['/workers?status=blocked']) });
    const blockedRow = await screen.findByText('title-w1');
    const blockedScope = within((blockedRow.closest('tr') ?? blockedRow.closest('div')) as HTMLElement);
    expect(blockedScope.getByRole('button', { name: 'Retry' })).toBeInTheDocument();

    render(<WorkersPage />, { wrapper: wrapper(['/workers?status=queued']) });
    const queuedRow = await screen.findByText('title-w2');
    const queuedScope = within((queuedRow.closest('tr') ?? queuedRow.closest('div')) as HTMLElement);
    expect(queuedScope.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(queuedScope.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });
});

function WorkerIdMarker() {
  const { id } = useParams();
  return <div>worker {id}</div>;
}

function SearchMarker() {
  const location = useLocation();
  return <div>search{location.search}</div>;
}

describe('legacy redirects', () => {
  function redirectWrapper(initialEntries: string[]) {
    return function Wrapper({ children }: { children: ReactNode }) {
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      });
      return (
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
        </QueryClientProvider>
      );
    };
  }

  it('redirects /tasks/:id to /workers/:id', async () => {
    render(
      <Routes>
        <Route path="/tasks/:id" element={<TaskIdRedirect />} />
        <Route path="/workers/:id" element={<WorkerIdMarker />} />
      </Routes>,
      { wrapper: redirectWrapper(['/tasks/fleet-abc']) },
    );
    expect(await screen.findByText('worker fleet-abc')).toBeInTheDocument();
  });

  it('redirects /schedules/:id into the Scheduled sub-tab', async () => {
    render(
      <Routes>
        <Route path="/schedules/:id" element={<ScheduleIdRedirect />} />
        <Route path="/workers" element={<SearchMarker />} />
      </Routes>,
      { wrapper: redirectWrapper(['/schedules/sched-1']) },
    );
    expect(await screen.findByText('search?tab=scheduled&schedule=sched-1')).toBeInTheDocument();
  });
});

describe('Runs history Load more', () => {
  function mockHistory(tasks: TaskSummary[]) {
    const tasksSpy = vi.spyOn(api, 'getTasks').mockResolvedValue(tasks);
    vi.spyOn(api, 'getSchedules').mockResolvedValue([]);
    vi.spyOn(api, 'listWorkflows').mockResolvedValue([]);
    vi.spyOn(api, 'getAnalyticsSummary').mockResolvedValue(mockSummary());
    vi.spyOn(api, 'getChatQuestions').mockResolvedValue(mockQuestions(0));
    return tasksSpy;
  }

  it('widens the closed-task window through ?closed_limit=', async () => {
    const tasksSpy = mockHistory([makeTask({ id: 'd1', status: 'closed' })]);
    render(<WorkersPage />, { wrapper: wrapper(['/workers?status=done']) });

    expect(await screen.findByText('title-d1')).toBeInTheDocument();
    expect(screen.getByText('Showing up to 300 closed workers')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await waitFor(() => expect(tasksSpy).toHaveBeenCalledWith(600));
    expect(await screen.findByText('Showing up to 600 closed workers')).toBeInTheDocument();
  });

  it('hides Load more on the running filter', async () => {
    mockHistory([makeTask({ id: 'w1', status: 'in_progress' })]);
    render(<WorkersPage />, { wrapper: wrapper(['/workers']) });

    expect(await screen.findByText('title-w1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });
});
