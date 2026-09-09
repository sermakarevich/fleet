/**
 * Event-kind colors: one map for every timeline, gutter and live view.
 * Task-status colors live in shared/status.ts; this module owns the
 * orthogonal concept (what kind of event a row is, not how a task is
 * doing). Called by EventsTab, ActivityGutter and LiveTab.
 */

// Event-kind colors: union of the previous ActivityGutter (task/tool events)
// and EventsTab (session-level events) maps. Where both defined a color for
// the same kind they already agreed.
const KIND_COLORS: Record<string, string> = {
  tool_use: '#3b82f6',
  tool_result: '#22c55e',
  api_request: '#8b5cf6',
  api_response: '#a855f7',
  message: '#f59e0b',
  error: '#ef4444',
  assistant_text: '#22c55e',
  thinking: '#6366f1',
  session_started: '#a78bfa',
  session_ended: '#94a3b8',
};

/** Color for one event kind, grey when the kind is unknown. */
export function eventKindColor(kind: string): string {
  return KIND_COLORS[kind] ?? '#71717a';
}
