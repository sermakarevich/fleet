/**
 * Polling cadences for every react-query refetchInterval in the UI.
 * Detail tabs (Events/Log/Stderr/Files/Diff) disable polling while the
 * events socket is connected (see usePoll below) because the socket
 * already streams the same updates. List queries that the socket only
 * patches (tasks list: lease, beads status) keep a slow fallback poll
 * while connected — see usePollWithSocketFallback.
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

/**
 * Polling interval that stays live while the shared events socket is
 * connected: returns the connected-speed interval then, the
 * disconnected-speed interval when the socket is down, or false when
 * disabled. Used by list queries (tasks list, single task) whose
 * lease/beads-status fields the socket overlays never patch, so a pure
 * socket feed would leave them frozen.
 */
export function usePollWithSocketFallback(
  disconnectedSpeed: PollSpeed,
  connectedSpeed: PollSpeed,
  enabled = true,
): number | false {
  const socketConnected = useSocketStatus();
  if (!enabled) return false;
  return socketConnected ? POLL[connectedSpeed] : POLL[disconnectedSpeed];
}
