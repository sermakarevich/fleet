/**
 * Tests for the new-worker panel: the Run now/schedule switch, the
 * schedule fields (cron + preset picker) and submit payloads for both
 * modes.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import { api } from '../../shared/api';
import { NewWorkerPanel } from './NewWorkerPanel';

afterEach(cleanup);

afterEach(() => {
  vi.restoreAllMocks();
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}

function mockLookups() {
  vi.spyOn(api, 'getCoders').mockResolvedValue({ coders: [] });
  vi.spyOn(api, 'getTemplates').mockResolvedValue({ templates: [] });
  vi.spyOn(api, 'getTasks').mockResolvedValue([]);
  vi.spyOn(api, 'previewCron').mockResolvedValue({ valid: true, error: null, upcoming: [] });
}

describe('NewWorkerPanel', () => {
  it('runs now by default and posts to POST /api/tasks', async () => {
    mockLookups();
    const createSpy = vi.spyOn(api, 'createTask').mockResolvedValue({ id: 'fleet-new' });
    const onCreated = vi.fn();
    render(<NewWorkerPanel onClose={vi.fn()} onCreated={onCreated} />, { wrapper });

    fireEvent.change(screen.getByPlaceholderText('What should this worker do?'), {
      target: { value: 'do the thing' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create worker' }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'do the thing' }),
    ));
    expect(onCreated).toHaveBeenCalledWith('fleet-new');
  });

  it('shows cron + preset picker on a schedule and posts target=task', async () => {
    mockLookups();
    const scheduleSpy = vi.spyOn(api, 'createSchedule').mockResolvedValue({ id: 'sched-1' } as never);
    const createSpy = vi.spyOn(api, 'createTask').mockResolvedValue({ id: 'fleet-new' });
    render(<NewWorkerPanel onClose={vi.fn()} onCreated={vi.fn()} />, { wrapper });

    // Schedule fields hidden until the switch flips.
    expect(screen.queryByPlaceholderText('0 9 * * 1-5')).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('on a schedule'));
    const cronInput = await screen.findByPlaceholderText('0 9 * * 1-5');
    expect(screen.getByLabelText('Cron preset')).toBeInTheDocument();

    // Preset picker fills the cron field.
    fireEvent.change(screen.getByLabelText('Cron preset'), { target: { value: '0 9 * * *' } });
    expect(cronInput).toHaveValue('0 9 * * *');

    fireEvent.change(screen.getByPlaceholderText('What should this worker do?'), {
      target: { value: 'nightly triage' },
    });
    // Cron preview is debounced: wait for the check to run and settle
    // (valid) before submitting.
    await screen.findByText('Checking schedule…');
    await waitFor(() => expect(screen.queryByText('Checking schedule…')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Create schedule' }));

    await waitFor(() => expect(scheduleSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        cron: '0 9 * * *',
        target: 'task',
        enabled: true,
        title: 'nightly triage',
      }),
    ));
    expect(createSpy).not.toHaveBeenCalled();
  });
});
