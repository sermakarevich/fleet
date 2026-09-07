// Single home for status -> color/label and event-kind -> color mappings.
// Previously forked 3 ways (Tasks.tsx, BD.tsx, TaskDetail/Header.tsx) with
// inconsistent colors for the same status; this is now the one source.

export interface StatusStyle {
  bg: string;
  fg: string;
}

const STATUS_STYLES: Record<string, StatusStyle> = {
  in_progress: { bg: '#16a34a', fg: '#fff' },
  blocked: { bg: '#d97706', fg: '#fff' },
  open: { bg: '#2563eb', fg: '#fff' },
  ready: { bg: '#2563eb', fg: '#fff' },
  deferred: { bg: '#6b7280', fg: '#fff' },
  closed: { bg: '#27272a', fg: '#71717a' },
  failed: { bg: '#dc2626', fg: '#fff' },
};

const DEFAULT_STYLE: StatusStyle = { bg: '#3f3f46', fg: '#a1a1aa' };

export function statusColor(status: string): StatusStyle {
  return STATUS_STYLES[status] ?? DEFAULT_STYLE;
}

const STATUS_LABELS: Record<string, string> = {
  in_progress: 'In progress',
  blocked: 'Blocked',
  open: 'Open',
  ready: 'Ready',
  deferred: 'Deferred',
  closed: 'Closed',
  failed: 'Failed',
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

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

export function eventKindColor(kind: string): string {
  return KIND_COLORS[kind] ?? '#71717a';
}
