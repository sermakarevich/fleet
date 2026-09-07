import { statusColor, statusLabel } from '../../shared/status';

export interface ChipStyle { label: string; bg: string; fg: string }

// "Stopping…" is a transient client-side overlay on top of the canonical
// status, not a status value of its own, so it lives here rather than
// in shared/status.ts.
export function chipFor(status: string, stopping = false): ChipStyle {
  if (stopping) return { label: 'Stopping…', bg: '#92400e', fg: '#fff' };
  const { bg, fg } = statusColor(status);
  return { label: statusLabel(status), bg, fg };
}
