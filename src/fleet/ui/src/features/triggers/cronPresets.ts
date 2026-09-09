/**
 * Cron preset table for the trigger form's preset picker.
 * A table (not an if-chain) of label + 5-field expression.
 * Called by TriggerForm; covered by cronPresets.test.ts.
 */

// One preset row: human label plus its cron expression.
export interface CronPreset {
  label: string;
  expression: string;
}

// Preset picker options, most frequent first.
export const CRON_PRESETS: CronPreset[] = [
  { label: 'Every 15 minutes', expression: '*/15 * * * *' },
  { label: 'Hourly', expression: '0 * * * *' },
  { label: 'Daily 09:00', expression: '0 9 * * *' },
  { label: 'Weekdays 09:00', expression: '0 9 * * 1-5' },
  { label: 'Weekly Monday 09:00', expression: '0 9 * * 1' },
  { label: 'Monthly 1st 09:00', expression: '0 9 1 * *' },
];
