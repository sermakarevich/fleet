export function fmtDuration(sec: number | null): string {
  if (sec == null) return '\u2014';
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

export function fmtTokens(n: number | null): string {
  if (n == null) return '\u2014';
  if (n === 0) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${n >= 10_000 ? (n / 1_000).toFixed(0) : (n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function fmtPct(x: number | null): string {
  if (x == null) return '\u2014';
  return `${Math.round(x * 100)}%`;
}

export function fmtCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
