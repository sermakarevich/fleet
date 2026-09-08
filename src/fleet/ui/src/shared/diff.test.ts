/**
 * Unit tests for shared/diff.ts computeLineDiff.
 */
import { describe, expect, it } from 'vitest';
import { computeLineDiff } from './diff';

describe('computeLineDiff', () => {
  it('marks identical texts fully equal', () => {
    expect(computeLineDiff('a\nb', 'a\nb')).toEqual([
      { type: 'equal', text: 'a' },
      { type: 'equal', text: 'b' },
    ]);
  });

  it('returns no lines for two empty inputs', () => {
    expect(computeLineDiff('', '')).toEqual([]);
  });

  it('treats empty old text as a pure addition', () => {
    expect(computeLineDiff('', 'x\ny')).toEqual([
      { type: 'add', text: 'x' },
      { type: 'add', text: 'y' },
    ]);
  });

  it('treats empty new text as a pure removal', () => {
    expect(computeLineDiff('x\ny', '')).toEqual([
      { type: 'remove', text: 'x' },
      { type: 'remove', text: 'y' },
    ]);
  });

  it('orders a changed middle line as remove then add', () => {
    expect(computeLineDiff('a\nb\nc', 'a\nB\nc')).toEqual([
      { type: 'equal', text: 'a' },
      { type: 'remove', text: 'b' },
      { type: 'add', text: 'B' },
      { type: 'equal', text: 'c' },
    ]);
  });

  it('falls back to flat remove+add past the line cap', () => {
    const oldStr = Array.from({ length: 401 }, (_, i) => `old-${i}`).join('\n');
    const lines = computeLineDiff(oldStr, 'new');
    expect(lines).toHaveLength(402);
    expect(lines[0]).toEqual({ type: 'remove', text: 'old-0' });
    expect(lines[401]).toEqual({ type: 'add', text: 'new' });
  });
});
