/**
 * Polling cadences for every react-query refetchInterval in the UI.
 * Called by useApi hooks and task-detail tabs; intervals are disabled
 * while the events socket is connected (see usePoll below) because the
 * socket already streams the same updates.
 */
import { useSocketStatus } from './hooks/useEventSocket';

/** Polling cadences: fast for detail/inbox, normal for lists, slow for analytics/health. */
export const POLL = {
  fast: 3000,
  normal: 5000,
  slow: 30000,
} as const;

export type PollSpeed = keyof typeof POLL;

/** Interval for one speed, or false when polling should pause. */
export function pollInterval(speed: PollSpeed, enabled: boolean): number | false {
  return enabled ? POLL[speed] : false;
}

/**
 * Polling interval for one speed, false while the shared events socket is
 * connected. Pass enabled=false (e.g. task finished) to pause polling
 * even when the socket is down.
 */
export function usePoll(speed: PollSpeed, enabled = true): number | false {
  const socketConnected = useSocketStatus();
  return pollInterval(speed, enabled && !socketConnected);
}
