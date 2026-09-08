/**
 * One-second ticker plus relative-time formatting for chat questions.
 * Called by ChatPage (which passes `now` down so the whole tree ticks
 * together); QuestionList and AnswerForm read relTime.
 */
import { useEffect, useState } from 'react';

// Re-render the caller every intervalMs; returns the current epoch millis.
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

// Compact age like 5s, 3m, 2h, 4d from a unix-epoch-seconds timestamp.
export function relTime(ts: number, serverOffset: number, nowMs = Date.now()): string {
  const s = Math.max(0, Math.floor(nowMs / 1000 + serverOffset - ts));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
