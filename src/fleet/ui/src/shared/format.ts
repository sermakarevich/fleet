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
