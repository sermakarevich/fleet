import { useEffect, useRef, useState } from 'react';
import { getFleetToken } from '../api';
import type { FleetEvent } from '../types';

interface WsMessage {
  task_id: string;
  event: FleetEvent;
}

type EventCallback = (taskId: string, event: FleetEvent) => void;

export function useWebSocket(onEvent: EventCallback): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const baseUrl = `${protocol}//${window.location.host}/ws/events`;
    const token = getFleetToken();
    const url = token
      ? `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
      : baseUrl;
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
          const msg = JSON.parse(ev.data) as WsMessage;
          onEventRef.current(msg.task_id, msg.event);
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = () => {
        if (!cancelled) {
          setConnected(false);
          reconnectTimer = setTimeout(connect, 2000);
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
  }, []);

  return { connected };
}
