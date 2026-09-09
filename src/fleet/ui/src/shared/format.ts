// Single home for every timestamp/duration/token/count formatter used across
// the UI. Names say what they format; params say what they take (counts and
// values are never single letters).

/** "14:32" if `timestamp` is today, else "Jul 25 14:32". Used for started/ended timestamps. */
export function formatTimestamp(timestamp: string | null): string {
  if (!timestamp) return '—';
  const date = new Date(timestamp);
  const now = new Date();
  const pad = (part: number) => part.toString().padStart(2, '0');
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (date.toDateString() === now.toDateString()) return time;
  const month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][date.getMonth()];
  return `${month} ${date.getDate()} ${time}`;
}

/** "14:32:07" — always full clock time, no "today" shortcut. Used in dense event/run logs. */
export function formatClockTime(value: string | null): string {
  if (!value) return '—';
  try {
    const date = new Date(value.replace('Z', '+00:00'));
    if (isNaN(date.getTime())) return value;
    return date.toTimeString().slice(0, 8);
  } catch {
    return value;
  }
}

/** "1h 2m", "5m 3s", "42s", "0s", or "—" for null. */
export function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—';
  if (seconds === 0) return '0s';
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  if (hours === 0) {
    if (minutes === 0) return `${rest}s`;
    return `${minutes}m ${rest > 0 ? rest + 's' : ''}`.trim();
  }
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}m`;
}

/** Row/card context cell: "42%" if a percent is known, else "12k" / raw token count. */
export function formatTokens(tokenCount: number | null, percent: number | null = null): string {
  if (tokenCount == null) return '—';
  if (percent != null) return `${Math.round(percent)}%`;
  if (tokenCount === 0) return '0';
  if (tokenCount >= 1_000_000) return `${(tokenCount / 1_000_000).toFixed(1)}M`;
  if (tokenCount >= 1_000) return `${tokenCount >= 10_000 ? (tokenCount / 1_000).toFixed(0) : (tokenCount / 1_000).toFixed(1)}k`;
  return String(tokenCount);
}

/** Tooltip for the context cell: "142k / 1,048k" (used tokens / resolved window). */
export function formatContextTitle(tokenCount: number | null, tokenLimit: number | null): string | undefined {
  if (tokenCount == null || tokenLimit == null) return undefined;
  return `${compactCount(tokenCount)} / ${compactCount(tokenLimit)}`;
}

/** Compact token count without a percent: "142k", "1,048k", "2.0M". */
function compactCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${Math.round(count / 1_000).toLocaleString('en-US')}k`;
  return String(count);
}

/** "42%" from a 0..1 fraction, or "—" for null. */
export function formatPercent(fraction: number | null): string {
  if (fraction == null) return '—';
  return `${Math.round(fraction * 100)}%`;
}
/** Compact integer count for chart labels: "1.2M", "3.4k", "42". */
export function formatCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`;
  return String(count);
}

/** Whole-k context limit ("200k"); used for coder picker labels. */
export function formatKiloTokens(tokenCount: number): string {
  return `${Math.round(tokenCount / 1_000)}k`;
}

/** Grouped integer ("12,345"), or "—" for null. */
export function formatInteger(value: number | null): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US');
}

/** Full local date+time ("7/25/2026, 2:32:00 PM"), or "—" for null. */
export function formatDateTime(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

/** "Jul 5" from a Date (chart ticks, end dates). */
export function formatMonthDay(date: Date): string {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** "Mon, Jul 28" from a Date (chart tooltips). */
export function formatWeekdayMonthDay(date: Date): string {
  return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

/** "14:32" (24-hour) from a Date. */
export function formatHourMinute(date: Date): string {
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

/** "Jul 05 14:32" from an ISO string; returns the input when unparseable. */
export function formatShortDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const month = date.toLocaleString('en-US', { month: 'short' });
  const day = String(date.getDate()).padStart(2, '0');
  return `${month} ${day} ${formatHourMinute(date)}`;
}

/** Idle age ("just now", "12s ago", "3m ago"), or "—" for null. */
export function formatIdle(seconds: number | null): string {
  if (seconds == null) return '—';
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}

/** Compact age ("5s", "3m", "2h", "4d") from a unix-epoch-seconds timestamp. */
export function formatRelativeAge(timestampSec: number, serverOffsetSec: number, nowMs = Date.now()): string {
  const ageSec = Math.max(0, Math.floor(nowMs / 1000 + serverOffsetSec - timestampSec));
  if (ageSec < 60) return `${ageSec}s`;
  if (ageSec < 3600) return `${Math.floor(ageSec / 60)}m`;
  if (ageSec < 86400) return `${Math.floor(ageSec / 3600)}h`;
  return `${Math.floor(ageSec / 86400)}d`;
}
