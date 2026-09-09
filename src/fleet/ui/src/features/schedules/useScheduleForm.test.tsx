/**
 * Unit tests for the schedule form hook: submit stays disabled until the
 * form is valid, and edit mode pre-fills every field from the schedule.
 */
import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { ToastProvider } from '../../shared/contexts/ToastContext';
import type { Schedule } from '../../shared/types';
import { useScheduleForm } from './useScheduleForm';

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

function makeSchedule(): Schedule {
  return {
    id: 'sched-9',
    name: 'nightly-triage',
    cron: '0 9 * * 1-5',
    timezone: 'Europe/Warsaw',
    enabled: false,
    title: 'Triage {date}',
    description: 'Look at the inbox',
    cwd: '/repo',
    coder: 'claude',
    model: 'sonnet',
    priority: 2,
    overlap: 'queue',
    target: 'task',
    workflow_id: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    next_fire_at: null,
    run_count: 0,
    last_run: null,
  };
}

describe('useScheduleForm', () => {
  it('submit is disabled until name, valid cron and title are present', async () => {
    const { result } = renderHook(
      () => useScheduleForm({ onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.canSubmit).toBe(false);
    act(() => {
      result.current.setName('nightly');
      result.current.setTitle('Triage {date}');
      result.current.setCron('0 9 * * 1-5');
    });
    // The cron preview fetch has no backend here, so the preview is not
    // valid and submit must stay disabled.
    expect(result.current.canSubmit).toBe(false);
  });

  it('edit mode pre-fills from the schedule', () => {
    const schedule = makeSchedule();
    const { result } = renderHook(
      () => useScheduleForm({ initial: schedule, onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.isEdit).toBe(true);
    expect(result.current.name).toBe('nightly-triage');
    expect(result.current.cron).toBe('0 9 * * 1-5');
    expect(result.current.timezone).toBe('Europe/Warsaw');
    expect(result.current.title).toBe('Triage {date}');
    expect(result.current.description).toBe('Look at the inbox');
    expect(result.current.cwd).toBe('/repo');
    expect(result.current.coder).toBe('claude');
    expect(result.current.model).toBe('sonnet');
    expect(result.current.priority).toBe(2);
    expect(result.current.overlap).toBe('queue');
    expect(result.current.enabled).toBe(false);
  });

  it('create mode defaults to enabled with skip overlap', () => {
    const { result } = renderHook(
      () => useScheduleForm({ onSaved: () => undefined, onClose: () => undefined }),
      { wrapper },
    );
    expect(result.current.isEdit).toBe(false);
    expect(result.current.enabled).toBe(true);
    expect(result.current.overlap).toBe('skip');
  });
});
