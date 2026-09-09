import { fmtMonthDay, fmtWeekdayMonthDay } from '../../shared/format';

const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;
const MAX_FILL = 400;

/**
 * Zero-fill gaps in a time-bucketed series so the x-axis is a continuous
 * timeline. The server only emits buckets that contain data, which makes a
 * categorical axis silently skip empty hours/days.
 *
 * Buckets are keyed by ISO strings on UTC boundaries ("2026-07-25" for days,
 * "2026-07-25T14:00:00+00:00" for hours). `windowDays > 0` extends the fill
 * back to the window start so a quiet week reads as quiet; 0 (all-time)
 * fills only between the first and last data points.
 */
export function fillBuckets<T extends { bucket: string }>(
  buckets: T[],
  bucketSize: 'hour' | 'day',
  zero: Omit<T, 'bucket'>,
  windowDays: number,
): T[] {
  const step = bucketSize === 'hour' ? HOUR_MS : DAY_MS;
  const byMs = new Map<number, T>();
  for (const b of buckets) {
    const ms = Date.parse(b.bucket);
    if (!Number.isNaN(ms)) byMs.set(ms, b);
  }
  if (byMs.size === 0) return [];

  const dataMs = [...byMs.keys()];
  const end = Math.floor(Date.now() / step) * step;
  let start = Math.min(...dataMs);
  if (windowDays > 0) {
    start = Math.min(start, end - windowDays * DAY_MS + step);
  }
  if ((end - start) / step > MAX_FILL) {
    return [...byMs.entries()].sort((a, b) => a[0] - b[0]).map(e => e[1]);
  }

  const out: T[] = [];
  for (let ms = start; ms <= end; ms += step) {
    const existing = byMs.get(ms);
    out.push(existing ?? ({ ...zero, bucket: new Date(ms).toISOString() } as T));
  }
  return out;
}

/** Short x-axis tick for a bucket: "14:00" for hours, "Jul 25" for days. */
export function bucketTickLabel(bucketSize: 'hour' | 'day', iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (bucketSize === 'hour') {
    return `${String(d.getHours()).padStart(2, '0')}:00`;
  }
  return fmtMonthDay(d);
}

/** Full tooltip label: "Mon, Jul 28, 14:00" for hours, "Mon, Jul 28" for days. */
export function bucketTooltipLabel(bucketSize: 'hour' | 'day', iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const day = fmtWeekdayMonthDay(d);
  if (bucketSize === 'hour') {
    return `${day}, ${String(d.getHours()).padStart(2, '0')}:00`;
  }
  return day;
}
