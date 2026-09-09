/**
 * Tests for the shared polling cadences: list queries keep a slow
 * fallback poll while the events socket is connected (their lease /
 * beads-status fields are never patched by socket overlays), while
 * detail-tab polling via usePoll still pauses when the socket is up.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import { POLL, usePoll, usePollWithSocketFallback } from './poll';
import { useEventSocket } from './hooks/useEventSocket';

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
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPollHooks() {
  const socket = renderHook(() => useEventSocket('/ws/events', () => {}));
  const poll = renderHook(() => usePollWithSocketFallback('normal', 'slow'));
  const legacy = renderHook(() => usePoll('normal'));
  return { socket, poll, legacy };
}

describe('usePollWithSocketFallback', () => {
  it('returns the normal interval while the socket is down', () => {
    const { socket, poll } = renderPollHooks();
    expect(poll.result.current).toBe(POLL.normal);
    socket.unmount();
    poll.unmount();
  });

  it('returns the slow interval (not false) while the socket is connected', () => {
    const { socket, poll } = renderPollHooks();
    act(() => lastSocket().open());
    expect(poll.result.current).toBe(POLL.slow);
    expect(poll.result.current).not.toBe(false);
    socket.unmount();
    poll.unmount();
  });

  it('returns false when disabled, connected or not', () => {
    const disabled = renderHook(() => usePollWithSocketFallback('normal', 'slow', false));
    const socket = renderHook(() => useEventSocket('/ws/events', () => {}));
    expect(disabled.result.current).toBe(false);
    act(() => lastSocket().open());
    expect(disabled.result.current).toBe(false);
    socket.unmount();
    disabled.unmount();
  });

  it('goes back to normal after the socket drops', () => {
    const { socket, poll } = renderPollHooks();
    act(() => lastSocket().open());
    expect(poll.result.current).toBe(POLL.slow);
    act(() => lastSocket().close());
    expect(poll.result.current).toBe(POLL.normal);
    socket.unmount();
    poll.unmount();
  });
});

describe('usePoll (detail tabs)', () => {
  it('still pauses while the socket is connected', () => {
    const { socket, legacy } = renderPollHooks();
    expect(legacy.result.current).toBe(POLL.normal);
    act(() => lastSocket().open());
    expect(legacy.result.current).toBe(false);
    socket.unmount();
    legacy.unmount();
  });
});
