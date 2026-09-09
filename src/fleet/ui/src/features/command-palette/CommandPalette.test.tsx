/**
 * Tests for the command palette worker jump: cached workers match by
 * title/id, and an unknown id still offers a direct jump to
 * /workers/:id so closed beads beyond the history window stay reachable.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { api } from '../../shared/api';
import type { TaskSummary } from '../../shared/types';
import { CommandPalette } from './CommandPalette';

afterEach(cleanup);

beforeEach(() => {
  vi.spyOn(api, 'search').mockResolvedValue([]);
  // cmdk observes list size and scrolls items; jsdom has neither.
  vi.stubGlobal('ResizeObserver', class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  });
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

function wrapper(seed: TaskSummary[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    client.setQueryData(['tasks'], seed);
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/workers']}>
          {children}
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

function seedTask(partial: Partial<TaskSummary> & { id: string }): TaskSummary {
  return { title: `title-${partial.id}`, ...partial } as TaskSummary;
}

describe('CommandPalette schedule entries', () => {
  it('jumps to the scheduled workflows sub-tab', async () => {
    render(<CommandPalette open setOpen={() => {}} onCreateWorker={() => {}} />, {
      wrapper: wrapper([]),
    });

    fireEvent.click(await screen.findByText('Scheduled workflows'));
    expect(screen.getByTestId('location').textContent).toBe('/workflows?tab=scheduled');
  });

  it('New schedule asks for the target before navigating', async () => {
    render(<CommandPalette open setOpen={() => {}} onCreateWorker={() => {}} />, {
      wrapper: wrapper([]),
    });

    expect(screen.queryByText('Schedule a worker')).not.toBeInTheDocument();
    fireEvent.click(await screen.findByText('New schedule…'));
    fireEvent.click(await screen.findByText('Schedule a workflow'));
    expect(screen.getByTestId('location').textContent).toBe('/workflows?tab=scheduled&new=1');
  });
});

describe('CommandPalette worker jump', () => {
  it('jumps to an uncached bead id via /workers/:id', async () => {
    render(<CommandPalette open setOpen={() => {}} onCreateWorker={() => {}} />, {
      wrapper: wrapper([]),
    });

    fireEvent.change(
      screen.getByPlaceholderText('Jump to worker, run action, or search…'),
      { target: { value: 'fleet-xyz' } },
    );

    const item = await screen.findByText('Go to worker fleet-xyz');
    fireEvent.click(item);
    expect(screen.getByTestId('location').textContent).toBe('/workers/fleet-xyz');
  });

  it('does not offer the id jump for an id already in the cache', async () => {
    render(<CommandPalette open setOpen={() => {}} onCreateWorker={() => {}} />, {
      wrapper: wrapper([seedTask({ id: 'w1' })]),
    });

    fireEvent.change(
      screen.getByPlaceholderText('Jump to worker, run action, or search…'),
      { target: { value: 'w1' } },
    );

    expect(await screen.findByText('title-w1')).toBeInTheDocument();
    expect(screen.queryByText('Go to worker w1')).not.toBeInTheDocument();
  });
});
