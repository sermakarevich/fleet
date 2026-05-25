import { useEffect, useRef, useState } from 'react';
import type { FleetEvent } from '../types';

interface TaskWsMessage {
  event: FleetEvent;
}

type EventCallback = (event: FleetEvent) => void;

export function useTaskWebSocket(taskId: string, onEvent: EventCallback): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/tasks/${taskId}/events`;
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function connect() {
      ws = new WebSocket(url);

      ws.onopen = () => {
        if (!cancelled) setConnected(true);
      };

      ws.onmessage = (ev: MessageEvent<string>) => {
        try {
          const msg = JSON.parse(ev.data) as TaskWsMessage;
          onEventRef.current(msg.event);
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = (ev) => {
        if (!cancelled) {
          setConnected(false);
          // 4004 = task not found; don't reconnect
          if (ev.code !== 4004) {
            reconnectTimer = setTimeout(connect, 2000);
          }
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [taskId]);

  return { connected };
}
