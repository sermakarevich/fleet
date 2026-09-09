/**
 * Unit tests for the event-trigger form: the payload builder shapes the
 * request (blank optionals omitted, labels split, blank params dropped)
 * and the modal submits the expected payload on create.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import type { EventTrigger } from '../../shared/types';
import { EventTriggerForm, buildEventTriggerPayload } from './EventTriggerForm';

afterEach(cleanup);

function wrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter>{children}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  };
}

function savedTrigger(): EventTrigger {
  return {
    id: 'trig-9',
    name: 'blocked-investigator',
    source: 'blocked_task',
    title: 'Investigate X',
    description: '',
    source_params: {},
    enabled: true,
    target: 'task',
    cwd: null,
    coder: null,
    model: null,
    priority: 2,
    isolation: null,
    labels: [],
    max_open: 2,
    cooldown_sec: 0,
    created_at: '2026-09-09T10:00:00Z',
    updated_at: '2026-09-09T10:00:00Z',
    firing_count: 0,
    last_fired_at: null,
  };
}

beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
  vi.spyOn(api, 'listTriggerSources').mockResolvedValue([
    { kind: 'blocked_task', params: { fleet_blocked_only: 'only fleet-blocked beads (true/false)' } },
  ]);
  vi.spyOn(api, 'getCoders').mockResolvedValue({ coders: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('buildEventTriggerPayload', () => {
  it('omits blank optionals and splits labels on commas', () => {
    expect(
      buildEventTriggerPayload({
        name: '  blocked-investigator ',
        source: 'blocked_task',
        sourceParams: { fleet_blocked_only: 'true', other: '' },
        enabled: true,
        title: '  Investigate {{event.task_id}} ',
        description: '',
        cwd: '',
        coder: '',
        model: '',
        priority: 2,
        isolation: '',
        labels: 'triage, auto ,',
        maxOpen: 2,
        cooldownSec: 0,
      }),
    ).toEqual({
      name: 'blocked-investigator',
      source: 'blocked_task',
      source_params: { fleet_blocked_only: 'true' },
      enabled: true,
      title: 'Investigate {{event.task_id}}',
      priority: 2,
      labels: ['triage', 'auto'],
      max_open: 2,
      cooldown_sec: 0,
    });
  });
});

describe('EventTriggerForm', () => {
  it('renders source params from the picked source help map and submits the payload', async () => {
    const createSpy = vi.spyOn(api, 'createTrigger').mockResolvedValue(savedTrigger());
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<EventTriggerForm onClose={onClose} onSaved={onSaved} />, { wrapper: wrapper() });

    fireEvent.change(screen.getByPlaceholderText('blocked-investigator'), {
      target: { value: 'blocked-investigator' },
    });
    // Wait for the sources to load before picking one (a select with no
    // matching option yet would reset the change to blank).
    await screen.findByText('blocked_task');
    fireEvent.change(screen.getByLabelText('Source'), {
      target: { value: 'blocked_task' },
    });
    // The source's params render as inputs with the help text shown.
    expect(
      await screen.findByText('only fleet-blocked beads (true/false)'),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Source param fleet_blocked_only'), {
      target: { value: 'true' },
    });
    fireEvent.change(screen.getByPlaceholderText(/Investigate/), {
      target: { value: 'Investigate {{event.task_id}}' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'New trigger' }));

    await waitFor(() =>
      expect(createSpy).toHaveBeenCalledWith({
        name: 'blocked-investigator',
        source: 'blocked_task',
        source_params: { fleet_blocked_only: 'true' },
        enabled: true,
        title: 'Investigate {{event.task_id}}',
        priority: 2,
        max_open: 2,
        cooldown_sec: 0,
      }),
    );
    expect(onSaved).toHaveBeenCalledWith(savedTrigger());
    expect(onClose).toHaveBeenCalled();
  });

  it('stays disabled until the required fields are filled', async () => {
    vi.spyOn(api, 'createTrigger').mockResolvedValue(savedTrigger());
    render(<EventTriggerForm onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper: wrapper() });

    // Sources load async; the submit starts disabled with empty fields.
    await screen.findByText('blocked_task');
    expect(screen.getByRole('button', { name: 'New trigger' })).toBeDisabled();
  });
});
