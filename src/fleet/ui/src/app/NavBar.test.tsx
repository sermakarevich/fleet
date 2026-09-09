// Four-tab nav bar (ADR 0009 UI 7/7): exactly Workers, Workflows,
// Inbox, Settings in that order, a "+ New worker" button, the events
// connection dot, and a stale chip with a Restart action behind Confirm.
// Rendered by AppInner above every page.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../shared/contexts/ToastContext';
import { api } from '../shared/api';
import { NavBar } from './NavBar';

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
  // NavBar sizes itself with a ResizeObserver; jsdom has none.
  vi.stubGlobal('ResizeObserver', class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  });
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
  vi.spyOn(api, 'getChatQuestions').mockResolvedValue({ now: 0, pending: [] } as never);
  vi.spyOn(api, 'getHealthz').mockResolvedValue({ stale: false } as never);
  vi.spyOn(api, 'getSupervisor').mockResolvedValue({ stale: false } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function wrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter initialEntries={['/workers']}>{children}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  };
}

function tabLabels(): string[] {
  const links = screen.getAllByRole('link').map(el => el.textContent ?? '');
  // First link is the "fleet" brand; the rest are the tabs.
  return links.slice(1);
}

describe('NavBar tabs', () => {
  it('renders exactly four tabs in ADR 0009 order', () => {
    render(<NavBar onNewWorker={() => {}} />, { wrapper: wrapper() });
    expect(tabLabels()).toEqual(['Workers', 'Workflows', 'Inbox', 'Settings']);
  });

  it('has no analytics link and keeps + New worker plus the connection dot', () => {
    render(<NavBar onNewWorker={() => {}} />, { wrapper: wrapper() });
    expect(screen.queryByRole('link', { name: /analytics/i })).toBeNull();
    expect(screen.getByRole('button', { name: '+ New worker' })).toBeInTheDocument();
    expect(screen.getByText(/connected|disconnected/)).toBeInTheDocument();
  });
});

describe('NavBar stale chip', () => {
  it('restarts the supervisor behind Confirm when stale', async () => {
    vi.mocked(api.getSupervisor).mockResolvedValue({ stale: true } as never);
    const restart = vi.spyOn(api, 'restartSupervisor').mockResolvedValue({
      pid: 42,
      alive: true,
      started_at: null,
    });
    render(<NavBar onNewWorker={() => {}} />, { wrapper: wrapper() });

    fireEvent.click(await screen.findByRole('button', { name: /stale/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(restart).toHaveBeenCalledTimes(1));
  });

  it('Cancel leaves the supervisor alone', async () => {
    vi.mocked(api.getSupervisor).mockResolvedValue({ stale: true } as never);
    const restart = vi.spyOn(api, 'restartSupervisor').mockResolvedValue({
      pid: 42,
      alive: true,
      started_at: null,
    });
    render(<NavBar onNewWorker={() => {}} />, { wrapper: wrapper() });

    fireEvent.click(await screen.findByRole('button', { name: /stale/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(restart).not.toHaveBeenCalled();
  });
});
