// Single home for status -> color/label.
// Event-kind colors live in shared/colors.ts (a different concept).
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
