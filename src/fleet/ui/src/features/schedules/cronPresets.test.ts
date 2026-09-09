/**
 * Unit tests for the cron preset table: every preset is a valid 5-field
 * expression with a non-empty label.
 */
import { describe, expect, it } from 'vitest';
import { CRON_PRESETS } from './cronPresets';

describe('CRON_PRESETS', () => {
  it('every preset has a label and a 5-field expression', () => {
    expect(CRON_PRESETS.length).toBeGreaterThan(0);
    for (const preset of CRON_PRESETS) {
      expect(preset.label.trim().length).toBeGreaterThan(0);
      expect(preset.expression.trim().split(/\s+/)).toHaveLength(5);
    }
  });

  it('expressions are unique', () => {
    const expressions = CRON_PRESETS.map((p) => p.expression);
    expect(new Set(expressions).size).toBe(expressions.length);
  });
});
