// Single home for every timestamp/duration/token/pct formatter used across the UI.

/** "14:32" if `iso` is today, else "Jul 25 14:32". Used for started/ended timestamps. */
export function fmtTs(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const now = new Date();
  const pad = (n: number) => n.toString().padStart(2, '0');
  const t = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return t;
  const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()];
  return `${mo} ${d.getDate()} ${t}`;
}

/** "14:32:07" — always full clock time, no "today" shortcut. Used in dense event/run logs. */
export function fmtClockTime(ts: string | null): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts.replace('Z', '+00:00'));
    if (isNaN(d.getTime())) return ts;
    return d.toTimeString().slice(0, 8);
  } catch {
    return ts;
  }
}

/** "1h 2m", "5m 3s", "42s", "0s", or "—" for null. */
export function fmtDuration(sec: number | null): string {
  if (sec == null) return '—';
  if (sec === 0) return '0s';
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h === 0) {
    if (m === 0) return `${r}s`;
    return `${m}m ${r > 0 ? r + 's' : ''}`.trim();
  }
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

/** Row/card context cell: "42%" if a percent is known, else "12k" / raw token count. */
export function fmtTokens(tokens: number | null, pct: number | null = null): string {
  if (tokens == null) return '—';
  if (pct != null) return `${Math.round(pct)}%`;
  if (tokens === 0) return '0';
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${tokens >= 10_000 ? (tokens / 1_000).toFixed(0) : (tokens / 1_000).toFixed(1)}k`;
  return String(tokens);
}

/** Tooltip for the context cell: "142k / 1,048k" (used tokens / resolved window). */
export function fmtContextTitle(tokens: number | null, limit: number | null): string | undefined {
  if (tokens == null || limit == null) return undefined;
  return `${fmtCompact(tokens)} / ${fmtCompact(limit)}`;
}

/** Compact token count without a percent: "142k", "1,048k", "2.0M". */
function fmtCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000).toLocaleString('en-US')}k`;
  return String(n);
}

/** "42%" from a 0..1 fraction, or "—" for null. */
export function fmtPct(x: number | null): string {
  if (x == null) return '—';
  return `${Math.round(x * 100)}%`;
}
/** Compact integer count for chart labels: "1.2M", "3.4k", "42". */
export function fmtCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/** Whole-k context limit ("200k"); used for coder picker labels. */
export function fmtKilo(n: number): string {
  return `${Math.round(n / 1_000)}k`;
}

/** Grouped integer ("12,345"), or "—" for null. */
export function fmtInt(n: number | null): string {
  if (n == null) return '—';
  return n.toLocaleString('en-US');
}

/** Full local date+time ("7/25/2026, 2:32:00 PM"), or "—" for null. */
export function fmtDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

/** "Jul 5" from a Date (chart ticks, end dates). */
export function fmtMonthDay(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** "Mon, Jul 28" from a Date (chart tooltips). */
export function fmtWeekdayMonthDay(d: Date): string {
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

/** "14:32" (24-hour) from a Date. */
export function fmtHourMinute(d: Date): string {
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

/** "Jul 05 14:32" from an ISO string; returns the input when unparseable. */
export function fmtShortDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const mon = d.toLocaleString('en-US', { month: 'short' });
  const dd = String(d.getDate()).padStart(2, '0');
  return `${mon} ${dd} ${fmtHourMinute(d)}`;
}

/** Idle age ("just now", "12s ago", "3m ago"), or "—" for null. */
export function fmtIdle(sec: number | null): string {
  if (sec == null) return '—';
  if (sec < 5) return 'just now';
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  return `${Math.floor(sec / 60)}m ago`;
}

/** Compact age ("5s", "3m", "2h", "4d") from a unix-epoch-seconds timestamp. */
export function relTime(ts: number, serverOffset: number, nowMs = Date.now()): string {
  const s = Math.max(0, Math.floor(nowMs / 1000 + serverOffset - ts));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
