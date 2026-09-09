/**
 * Unit tests for the schedules page: it lists only single-task schedules
 * (the "task" target filter) and points at the recurring tab for workflow
 * schedules.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import { SchedulesPage } from './SchedulesPage';

afterEach(cleanup);

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/schedules']}>{children}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
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

describe('SchedulesPage', () => {
  it('fetches only single-task schedules and links to the recurring tab', async () => {
    const listSpy = vi.spyOn(api, 'getSchedules').mockResolvedValue([]);
    render(<SchedulesPage />, { wrapper });
    await waitFor(() => expect(screen.getByText(/No schedules yet/)).toBeInTheDocument());

    expect(listSpy).toHaveBeenCalledWith('task');
    expect(screen.getByText(/recurring workflows have their own/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'tab' }).getAttribute('href')).toBe('/recurring');
  });
});
