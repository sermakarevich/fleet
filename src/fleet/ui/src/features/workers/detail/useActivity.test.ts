// Tests for the activity feed hook (ADR 0017): tail load, 2s cursor
// polling while in progress, final fetch on finish, error tolerance,
// and loadEarlier prepend.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import { api } from '../../../shared/api';
import type { ActivityItem, ActivityResponse } from '../../../shared/types';
import { useActivity } from './useActivity';

function makeItem(seq: number, partial?: Partial<ActivityItem>): ActivityItem {
  return {
    seq,
    ts: `2026-09-29T10:00:${String(seq).padStart(2, '0')}Z`,
    attempt: 1,
    source: 'event',
    kind: 'assistant_text',
    tool_name: null,
    usage: null,
    summary: `row ${seq}`,
    raw: {},
    ...partial,
  } as ActivityItem;
}

function makeResponse(items: ActivityItem[], partial?: Partial<ActivityResponse>): ActivityResponse {
  return {
    items,
    total: items.length,
    has_earlier: false,
    latest_attempt: 1,
    stderr: null,
    ...partial,
  } as ActivityResponse;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('useActivity', () => {
  it('first call is a tail request and items land in order', async () => {
    const spy = vi
      .spyOn(api, 'getActivity')
      .mockResolvedValue(makeResponse([makeItem(1), makeItem(0)]));
    const { result } = renderHook(() => useActivity('t1', 'closed'));
    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('t1', { limit: 200, minLevel: 'warning' });
    expect(result.current.items.map((i) => i.seq)).toEqual([0, 1]);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('polls every 2s with after=last seq and appends while in_progress', async () => {
    const spy = vi
      .spyOn(api, 'getActivity')
      .mockResolvedValueOnce(makeResponse([makeItem(0), makeItem(1)]))
      .mockResolvedValueOnce(makeResponse([makeItem(2)], { latest_attempt: 1 }));
    const { result } = renderHook(() => useActivity('t1', 'in_progress'));
    await act(async () => {});
    expect(result.current.items.map((i) => i.seq)).toEqual([0, 1]);

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenLastCalledWith('t1', { after: 1, limit: 200, minLevel: 'warning' });
    expect(result.current.items.map((i) => i.seq)).toEqual([0, 1, 2]);
  });

  it('does one final fetch when status closes, then stops the timer', async () => {
    const spy = vi
      .spyOn(api, 'getActivity')
      .mockResolvedValueOnce(makeResponse([makeItem(0)]))
      .mockResolvedValueOnce(makeResponse([makeItem(1)]))
      .mockResolvedValueOnce(makeResponse([makeItem(2)]));
    const { result, rerender } = renderHook(({ status }) => useActivity('t1', status), {
      initialProps: { status: 'in_progress' },
    });
    await act(async () => {});
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(2);

    rerender({ status: 'closed' });
    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(3);
    expect(spy).toHaveBeenLastCalledWith('t1', { after: 1, limit: 200, minLevel: 'warning' });
    expect(result.current.items.map((i) => i.seq)).toEqual([0, 1, 2]);

    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(3);
  });

  it('keeps items on error, sets error, and keeps polling', async () => {
    const spy = vi
      .spyOn(api, 'getActivity')
      .mockResolvedValueOnce(makeResponse([makeItem(0), makeItem(1)]))
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(makeResponse([makeItem(2)]));
    const { result } = renderHook(() => useActivity('t1', 'in_progress'));
    await act(async () => {});
    expect(result.current.items).toHaveLength(2);

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    await act(async () => {});
    expect(result.current.error).toBe('boom');
    expect(result.current.items.map((i) => i.seq)).toEqual([0, 1]);

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(3);
    expect(result.current.error).toBeNull();
    expect(result.current.items.map((i) => i.seq)).toEqual([0, 1, 2]);
  });

  it('loadEarlier sends before=first seq and prepends', async () => {
    const spy = vi
      .spyOn(api, 'getActivity')
      .mockResolvedValueOnce(makeResponse([makeItem(5), makeItem(6)], { has_earlier: true }))
      .mockResolvedValueOnce(makeResponse([makeItem(3), makeItem(4)], { has_earlier: false }));
    const { result } = renderHook(() => useActivity('t1', 'closed'));
    await act(async () => {});
    expect(result.current.hasEarlier).toBe(true);

    act(() => {
      result.current.loadEarlier();
    });
    await act(async () => {});
    expect(spy).toHaveBeenLastCalledWith('t1', { before: 5, limit: 200, minLevel: 'warning' });
    expect(result.current.items.map((i) => i.seq)).toEqual([3, 4, 5, 6]);
  });
});
