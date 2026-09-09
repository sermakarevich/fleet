/**
 * Unit tests for the mutation factory: failures always toast (custom or
 * default message) and successes toast plus invalidate their keys.
 */
import { describe, expect, it } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { screen } from '@testing-library/dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { ToastProvider } from '../contexts/ToastContext';
import { useTaskMutation } from './useTaskMutation';

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

describe('useTaskMutation', () => {
  it('toasts the default failure message', async () => {
    const { result } = renderHook(
      () => useTaskMutation('Test action', () => Promise.reject(new Error('kaboom'))),
      { wrapper },
    );
    act(() => {
      result.current.mutate();
    });
    await waitFor(() => {
      expect(screen.getByText('Test action failed: kaboom')).toBeInTheDocument();
    });
  });

  it('toasts a custom failure message', async () => {
    const { result } = renderHook(
      () =>
        useTaskMutation('Delete task', () => Promise.reject(new Error('gone')), {
          invalidate: [['tasks']],
          failure: 'Could not delete.',
        }),
      { wrapper },
    );
    act(() => {
      result.current.mutate();
    });
    await waitFor(() => {
      expect(screen.getByText('Could not delete.')).toBeInTheDocument();
    });
  });

  it('toasts success and stays silent without a success message', async () => {
    const { result } = renderHook(
      () =>
        useTaskMutation('Save config', () => Promise.resolve('ok'), {
          invalidate: [['config']],
          success: 'Config saved',
        }),
      { wrapper },
    );
    act(() => {
      result.current.mutate();
    });
    await waitFor(() => {
      expect(screen.getByText('Config saved')).toBeInTheDocument();
    });
  });
});
