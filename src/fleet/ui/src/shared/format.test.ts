// Tests for the idle-age formatter, including the hour/day ranges.
import { describe, expect, it } from 'vitest';
import { formatIdle } from './format';

describe('formatIdle', () => {
  it('formats seconds and minutes', () => {
    expect(formatIdle(null)).toBe('—');
    expect(formatIdle(0)).toBe('just now');
    expect(formatIdle(12)).toBe('12s ago');
    expect(formatIdle(180)).toBe('3m ago');
  });

  it('formats hours below 24h', () => {
    expect(formatIdle(3600)).toBe('1h ago');
    expect(formatIdle(7200)).toBe('2h ago');
    expect(formatIdle(86399)).toBe('23h ago');
  });

  it('formats days', () => {
    expect(formatIdle(86400)).toBe('1d ago');
    expect(formatIdle(172800)).toBe('2d ago');
  });
});
