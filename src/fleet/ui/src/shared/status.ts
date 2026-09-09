import * as T from './styles/tokens';
// Single home for status -> color/label.
// Event-kind colors live in shared/colors.ts (a different concept).
// Previously forked 3 ways (Tasks.tsx, BD.tsx, TaskDetail/Header.tsx) with
// inconsistent colors for the same status; this is now the one source.

export interface StatusStyle {
  bg: string;
  fg: string;
}

const STATUS_STYLES: Record<string, StatusStyle> = {
  in_progress: { bg: T.colors.green, fg: T.colors.white },
  blocked: { bg: T.colors.amberDark, fg: T.colors.white },
  open: { bg: T.colors.info, fg: T.colors.white },
  ready: { bg: T.colors.info, fg: T.colors.white },
  deferred: { bg: T.colors.gray, fg: T.colors.white },
  closed: { bg: T.colors.borderSubtle, fg: T.colors.textDim },
  failed: { bg: T.colors.redDark, fg: T.colors.white },
};

const DEFAULT_STYLE: StatusStyle = { bg: T.colors.border, fg: T.colors.textSecondary };

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
  running: 'Running',
  succeeded: 'Succeeded',
  attention: 'Attention',
  cancelled: 'Cancelled',
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

// Workflow run statuses (ADR 0008): derived, never hand-edited.
const RUN_STATUS_STYLES: Record<string, StatusStyle> = {
  running: { bg: T.colors.info, fg: T.colors.white },
  succeeded: { bg: T.colors.green, fg: T.colors.white },
  attention: { bg: T.colors.amberDark, fg: T.colors.white },
  cancelled: { bg: T.colors.gray, fg: T.colors.white },
};

/** Chip colors for a workflow run status; unknown statuses get the default. */
export function runStatusColor(status: string): StatusStyle {
  return RUN_STATUS_STYLES[status] ?? DEFAULT_STYLE;
}
