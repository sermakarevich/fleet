/**
 * Unit tests for the shared events socket: the backoff schedule and the
 * connect/reconnect behaviour (with a fake WebSocket and fake timers).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, type RenderHookResult } from '@testing-library/react';
import { backoffDelay, useEventSocket, useSocketStatus } from './useEventSocket';

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent<string>) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.({} as Event);
  }

  receive(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>);
  }

  close(code = 1006): void {
    this.onclose?.({ code });
  }
}

function lastSocket(): FakeSocket {
  return FakeSocket.instances[FakeSocket.instances.length - 1];
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeSocket);
  vi.useFakeTimers();
});

const mounted: Array<() => void> = [];

// renderHook keeps the socket mounted (and registered) until unmount, so
// track every mount and tear it down after each test.
function renderSocketHook<T>(path: string, onMessage: (msg: T) => void, options?: { noReconnectCodes?: number[] }) {
  const mountedHook = renderHook(() => useEventSocket<T>(path, onMessage, options));
  mounted.push(mountedHook.unmount);
  return mountedHook;
}

function renderStatusHook(): RenderHookResult<boolean, unknown> {
  const mountedHook = renderHook(() => useSocketStatus());
  mounted.push(mountedHook.unmount);
  return mountedHook;
}

afterEach(() => {
  mounted.splice(0).forEach((unmount) => unmount());
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('backoffDelay', () => {
  it('doubles from 1s and caps at 30s', () => {
    expect([0, 1, 2, 3, 4, 5, 6, 10].map(backoffDelay)).toEqual(
      [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000],
    );
  });

  it('treats negative attempts as the first attempt', () => {
    expect(backoffDelay(-1)).toBe(1000);
  });
});

describe('useEventSocket', () => {
  it('opens the socket and reports connected', () => {
    const onMessage = vi.fn();
    const { result } = renderSocketHook('/ws/events', onMessage);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(result.current.connected).toBe(false);
    act(() => lastSocket().open());
    expect(result.current.connected).toBe(true);
  });

  it('delivers parsed messages and ignores malformed frames', () => {
    const onMessage = vi.fn();
    renderSocketHook<{ n: number }>('/ws/events', onMessage);
    act(() => lastSocket().receive({ n: 1 }));
    expect(onMessage).toHaveBeenCalledWith({ n: 1 });
    act(() => {
      lastSocket().onmessage?.({ data: 'not json' } as MessageEvent<string>);
    });
    expect(onMessage).toHaveBeenCalledTimes(1);
  });

  it('reconnects with exponential backoff after a drop', () => {
    const onMessage = vi.fn();
    const { result } = renderSocketHook('/ws/events', onMessage);
    act(() => lastSocket().open());
    act(() => lastSocket().close());
    expect(result.current.connected).toBe(false);

    act(() => { vi.advanceTimersByTime(999); });
    expect(FakeSocket.instances).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(1); });
    expect(FakeSocket.instances).toHaveLength(2);

    act(() => lastSocket().close());
    act(() => { vi.advanceTimersByTime(1999); });
    expect(FakeSocket.instances).toHaveLength(2);
    act(() => { vi.advanceTimersByTime(1); });
    expect(FakeSocket.instances).toHaveLength(3);
  });

  it('does not reconnect for noReconnectCodes', () => {
    const onMessage = vi.fn();
    renderSocketHook('/ws/events', onMessage, { noReconnectCodes: [4004] });
    act(() => lastSocket().open());
    act(() => lastSocket().close(4004));
    act(() => { vi.advanceTimersByTime(60000); });
    expect(FakeSocket.instances).toHaveLength(1);
  });
});

describe('useSocketStatus', () => {
  it('is true while any socket is connected', () => {
    const onMessage = vi.fn();
    const { result } = renderStatusHook();
    expect(result.current).toBe(false);
    renderSocketHook('/ws/events', onMessage);
    act(() => lastSocket().open());
    expect(result.current).toBe(true);
    act(() => lastSocket().close());
    expect(result.current).toBe(false);
  });
});
