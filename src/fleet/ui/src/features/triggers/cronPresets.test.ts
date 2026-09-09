/**
 * Unit tests for the cron preset table: every preset is a valid 5-field
 * expression and labels are unique.
 * Moved with the table from features/schedules (ADR 0009 triggers).
 */
import { describe, expect, it } from 'vitest';
import { CRON_PRESETS } from './cronPresets';

describe('CRON_PRESETS', () => {
  it('lists unique labels with 5-field expressions', () => {
    expect(CRON_PRESETS.length).toBeGreaterThan(0);
    const labels = CRON_PRESETS.map((p) => p.label);
    expect(new Set(labels).size).toBe(labels.length);
    for (const preset of CRON_PRESETS) {
      expect(preset.label.trim().length).toBeGreaterThan(0);
      expect(preset.expression.trim().split(/\s+/)).toHaveLength(5);
    }
  });

  it('covers the weekday-morning run', () => {
    expect(CRON_PRESETS).toContainEqual({ label: 'Weekdays 09:00', expression: '0 9 * * 1-5' });
  });
});
