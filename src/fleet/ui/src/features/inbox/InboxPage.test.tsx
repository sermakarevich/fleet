// Tests for the inbox page (ADR 0009): pending list on the shared
// DataList, row select opens the answer form, triage chips, nav badge
// count, /inbox/:id full page and the legacy /chat redirect.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import type { ChatQuestion } from '../../shared/types';
import { ChatRedirect } from '../../app/App';
import { NavBar } from '../../app/NavBar';
import { InboxPage } from './InboxPage';
import { InboxDetailPage } from './InboxDetailPage';

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
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    },
  );
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

function makeQuestion(partial: Partial<ChatQuestion> & { id: string }): ChatQuestion {
  return {
    agent_id: 'worker-1',
    session_id: 'sess-1',
    prompt: `prompt for ${partial.id}`,
    options: null,
    multi_select: false,
    priority: 0,
    status: 'pending',
    answer: null,
    note: null,
    default_answer: null,
    timeout_s: null,
    answered_by: null,
    created_at: Date.now() / 1000 - 90,
    answered_at: null,
    task_id: null,
    context: null,
    ...partial,
  } as ChatQuestion;
}

function mockInbox(questions: ChatQuestion[]) {
  vi.spyOn(api, 'getChatQuestions').mockResolvedValue({ now: Date.now() / 1000, pending: questions });
  vi.spyOn(api, 'getTask').mockResolvedValue({ status: 'blocked' } as never);
}

function inboxWrapper(initialEntries: string[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  };
}

function renderInbox(initialEntries: string[] = ['/inbox']) {
  return render(
    <Routes>
      <Route path="/inbox" element={<InboxPage />} />
      <Route path="/inbox/:id" element={<InboxDetailPage />} />
      <Route path="/workers/:id" element={<div>worker marker</div>} />
    </Routes>,
    { wrapper: inboxWrapper(initialEntries) },
  );
}

describe('InboxPage pending list', () => {
  it('renders asked/from/kind/priority/prompt columns with one row per question', async () => {
    mockInbox([
      makeQuestion({ id: 'q1', agent_id: 'worker-1', task_id: 'fleet-abc', priority: 2 }),
      makeQuestion({ id: 'q2', prompt: 'Should I retry the failed step?' }),
    ]);
    renderInbox();

    expect(await screen.findByRole('heading', { name: /inbox/i })).toBeInTheDocument();
    expect(await screen.findByText('prompt for q1')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Pending' })).toHaveAttribute('aria-selected', 'true');
    for (const header of ['Asked', 'From', 'Kind', 'Priority', 'Prompt']) {
      expect(screen.getByText(header)).toBeInTheDocument();
    }
    expect(screen.getByText('Should I retry the failed step?')).toBeInTheDocument();
    // Fleet task id links to the worker detail page.
    expect(screen.getByRole('link', { name: 'fleet-abc' })).toHaveAttribute('href', '/workers/fleet-abc');
    // Plain agent id renders as text (row cell plus the auto-selected detail header).
    expect(screen.getAllByText('worker-1').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows the empty state when nothing is pending', async () => {
    mockInbox([]);
    renderInbox();

    expect(await screen.findByText('No pending questions.')).toBeInTheDocument();
  });
});

describe('InboxPage select opens the answer form', () => {
  it('clicking a row shows its options in the right pane and submits the answer', async () => {
    mockInbox([
      makeQuestion({ id: 'q1', prompt: 'First question?' }),
      makeQuestion({ id: 'q2', prompt: 'Pick one direction.', options: ['left', 'right'] }),
    ]);
    const answerSpy = vi.spyOn(api, 'answerChatQuestion').mockResolvedValue({ ok: true, status: 'answered' });
    renderInbox();

    // First question auto-selects: free-text form, no option radios yet.
    await screen.findByText('First question?');
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Pick one direction.'));
    expect(await screen.findByRole('radio', { name: 'left' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: 'right' }));
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));
    await waitFor(() => expect(answerSpy).toHaveBeenCalledWith('q2', 'right'));
  });

  it('triage proposals show a triage chip and the task status chip', async () => {
    mockInbox([
      makeQuestion({
        id: 'q9',
        agent_id: 'triage',
        task_id: 'fleet-abc',
        prompt: 'Task fleet-abc is blocked: deploy failed',
        options: ['retry', 'close'],
      }),
    ]);
    renderInbox();

    expect(await screen.findByText('triage')).toBeInTheDocument();
    expect(await screen.findByText('Blocked')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /worker fleet-abc/ })).toHaveAttribute(
      'href',
      '/workers/fleet-abc',
    );
  });
});

describe('InboxDetailPage', () => {
  it('renders the full-page answer form with a back link', async () => {
    mockInbox([makeQuestion({ id: 'q1', prompt: 'Answer me on mobile?' })]);
    renderInbox(['/inbox/q1']);

    expect(await screen.findByText('Answer me on mobile?')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Type your answer…')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '← Back to inbox' })).toHaveAttribute('href', '/inbox');
  });

  it('shows a gone message for an unknown id', async () => {
    mockInbox([makeQuestion({ id: 'q1' })]);
    renderInbox(['/inbox/nope']);

    expect(await screen.findByText('That question is already answered or gone.')).toBeInTheDocument();
  });
});

describe('Inbox nav badge and redirect', () => {
  function renderNav(pending: number) {
    vi.spyOn(api, 'getChatQuestions').mockResolvedValue({
      now: Date.now() / 1000,
      pending: Array.from({ length: pending }, (_, i) => makeQuestion({ id: `q${i}` })),
    });
    vi.spyOn(api, 'getSupervisor').mockResolvedValue({ stale: false } as never);
    vi.spyOn(api, 'getHealthz').mockResolvedValue({ stale: false } as never);
    return render(<NavBar onNewWorker={() => {}} />, { wrapper: inboxWrapper(['/inbox']) });
  }

  it('shows the pending count as a badge', async () => {
    renderNav(3);

    const badge = await screen.findByTitle('3 unanswered questions');
    expect(badge).toHaveTextContent('3');
    expect(screen.getByRole('link', { name: /inbox/i })).toHaveAttribute('href', '/inbox');
  });

  it('shows only a dot when the queue is empty', async () => {
    renderNav(0);

    expect(await screen.findByTitle('No pending questions')).toBeInTheDocument();
    expect(screen.queryByTitle(/unanswered question/)).not.toBeInTheDocument();
  });

  it('redirects the legacy /chat route to /inbox', async () => {
    render(
      <Routes>
        <Route path="/chat" element={<ChatRedirect />} />
        <Route path="/inbox" element={<div>inbox marker</div>} />
      </Routes>,
      { wrapper: inboxWrapper(['/chat']) },
    );

    expect(await screen.findByText('inbox marker')).toBeInTheDocument();
  });
});
