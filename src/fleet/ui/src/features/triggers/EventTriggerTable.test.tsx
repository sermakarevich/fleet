/**
 * Unit tests for the event-trigger table: rows render from listTriggers
 * with the source/policy/firing columns and row actions, plus the empty
 * state when no triggers exist.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import { formatShortDateTime } from '../../shared/format';
import type { EventTrigger } from '../../shared/types';
import { EventTriggerTable } from './EventTriggerTable';

afterEach(cleanup);

function wrapper(initialEntries: string[]) {
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

// Minimal event trigger; tests override the interesting fields.
function makeTrigger(overrides: Partial<EventTrigger> = {}): EventTrigger {
  return {
    id: 'trig-1',
    name: 'blocked-investigator',
    source: 'blocked_task',
    title: 'Investigate {{event.task_id}}',
    description: '',
    source_params: {},
    enabled: true,
    target: 'task',
    cwd: null,
    coder: 'claude',
    model: 'sonnet',
    priority: 2,
    isolation: null,
    labels: [],
    max_open: 2,
    cooldown_sec: 0,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    firing_count: 3,
    last_fired_at: '2026-09-09T10:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('EventTriggerTable', () => {
  it('renders rows from a mocked listTriggers with source and firing columns', async () => {
    const listSpy = vi.spyOn(api, 'listTriggers').mockResolvedValue([
      makeTrigger({ id: 't1', name: 'blocked-investigator' }),
    ]);
    render(<EventTriggerTable />, { wrapper: wrapper(['/workers?tab=triggered']) });

    expect(await screen.findByText('blocked-investigator')).toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByText('blocked_task')).toBeInTheDocument();
    expect(screen.getByText(formatShortDateTime('2026-09-09T10:00:00Z'))).toBeInTheDocument();
    // Row actions: enable/disable toggle, preview and delete.
    expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Preview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '+ New trigger' })).toBeInTheDocument();
  });

  it('renders "never" when the trigger has not fired yet', async () => {
    vi.spyOn(api, 'listTriggers').mockResolvedValue([
      makeTrigger({ id: 't2', name: 'fresh-trigger', firing_count: 0, last_fired_at: null }),
    ]);
    render(<EventTriggerTable />, { wrapper: wrapper(['/workers?tab=triggered']) });

    expect(await screen.findByText('fresh-trigger')).toBeInTheDocument();
    expect(screen.getByText('never')).toBeInTheDocument();
  });

  it('renders the empty state when there are no triggers', async () => {
    vi.spyOn(api, 'listTriggers').mockResolvedValue([]);
    render(<EventTriggerTable />, { wrapper: wrapper(['/workers?tab=triggered']) });
    expect(await screen.findByText(/No event triggers yet/)).toBeInTheDocument();
  });

  it('toggles enable/disable through the row action', async () => {
    vi.spyOn(api, 'listTriggers').mockResolvedValue([
      makeTrigger({ id: 't3', name: 'toggle-me' }),
    ]);
    const setSpy = vi.spyOn(api, 'setTriggerEnabled').mockResolvedValue({ ok: true });
    render(<EventTriggerTable />, { wrapper: wrapper(['/workers?tab=triggered']) });

    fireEvent.click(await screen.findByRole('button', { name: 'Disable' }));
    await waitFor(() => expect(setSpy).toHaveBeenCalledWith('t3', false));
  });
});
