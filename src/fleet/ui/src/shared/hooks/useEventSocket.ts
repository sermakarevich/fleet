/**
 * The one websocket hook for the whole UI (replaces useWebSocket and
 * useTaskWebSocket). Called by GlobalEvents, TasksPage and
 * TaskDetailPage; NavBar reads useSocketStatus for the connection dot.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { getFleetToken } from '../api';

/** First reconnect wait; doubles every attempt up to BACKOFF_MAX_MS. */
export const BACKOFF_BASE_MS = 1000;

/** Upper bound for the reconnect wait. */
export const BACKOFF_MAX_MS = 30000;

/** Reconnect wait for a 0-based attempt: 1s, 2s, 4s, … capped at 30s. */
export function backoffDelay(attempt: number): number {
  return Math.min(BACKOFF_BASE_MS * 2 ** Math.max(0, attempt), BACKOFF_MAX_MS);
}

export interface EventSocketOptions {
  /** Close codes that must not reconnect (e.g. 4004 task-not-found). */
  noReconnectCodes?: number[];
}

// Global registry of connected sockets; useSocketStatus re-renders on change.
const connectedSockets = new Set<string>();
const statusListeners = new Set<() => void>();
let socketSeq = 0;

function subscribeStatus(notify: () => void): () => void {
  statusListeners.add(notify);
  return () => {
    statusListeners.delete(notify);
  };
}

function snapshotStatus(): boolean {
  return connectedSockets.size > 0;
}

function setSocketConnected(id: string, connected: boolean): void {
  const had = connectedSockets.size > 0;
  if (connected) connectedSockets.add(id);
  else connectedSockets.delete(id);
  if ((connectedSockets.size > 0) !== had) {
    statusListeners.forEach((notify) => notify());
  }
}

/** True while any useEventSocket connection is open (polling pauses then). */
export function useSocketStatus(): boolean {
  return useSyncExternalStore(subscribeStatus, snapshotStatus, snapshotStatus);
}

function socketUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${window.location.host}${path}`;
  const token = getFleetToken();
  return token ? `${url}?token=${encodeURIComponent(token)}` : url;
}

/**
 * Open a JSON-message websocket at path; parse each frame and hand it to
 * onMessage. Reconnects with exponential backoff; returns the live
 * connection state for inline indicators.
 */
export function useEventSocket<T>(
  path: string,
  onMessage: (message: T) => void,
  options?: EventSocketOptions,
): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const idRef = useRef<string | null>(null);
  if (idRef.current === null) {
    socketSeq += 1;
    idRef.current = `socket-${socketSeq}`;
  }

  useEffect(() => {
    const id = idRef.current as string;
    const url = socketUrl(path);
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    let attempt = 0;

    function mark(connectedNow: boolean): void {
      if (cancelled) return;
      setConnected(connectedNow);
      setSocketConnected(id, connectedNow);
    }

    function connect(): void {
      if (cancelled) return;
      ws = new WebSocket(url);

      ws.onopen = () => {
        attempt = 0;
        mark(true);
      };

      ws.onmessage = (ev: MessageEvent<string>) => {
        try {
          onMessageRef.current(JSON.parse(ev.data) as T);
        } catch {
          // ignore malformed frames; the next frame still parses
        }
      };

      ws.onclose = (ev) => {
        mark(false);
        if (cancelled) return;
        if (optionsRef.current?.noReconnectCodes?.includes(ev.code)) return;
        const wait = backoffDelay(attempt);
        attempt += 1;
        reconnectTimer = setTimeout(connect, wait);
      };

      ws.onerror = () => {
        ws?.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      setSocketConnected(id, false);
      ws?.close();
    };
  }, [path]);

  return { connected };
}
