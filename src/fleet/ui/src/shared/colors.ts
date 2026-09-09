import * as T from './styles/tokens';
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
  tool_use: T.colors.accent,
  tool_result: T.colors.success,
  api_request: T.colors.violet,
  api_response: T.colors.purple,
  message: T.colors.amber,
  error: T.colors.danger,
  assistant_text: T.colors.success,
  thinking: T.colors.indigo,
  session_started: T.colors.lavender,
  session_ended: T.colors.slateLight,
};

/** Color for one event kind, grey when the kind is unknown. */
export function eventKindColor(kind: string): string {
  return KIND_COLORS[kind] ?? T.colors.textDim;
}
