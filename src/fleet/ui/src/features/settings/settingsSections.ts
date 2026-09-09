// The one table mapping every RuntimeConfig field to its settings
// section (ADR 0009). Rendered by SettingsPage via ConfigSection; the
// coverage test in SettingsPage.test.tsx asserts every field appears in
// exactly one section, and the Record type below fails tsc when the
// backend adds a field nobody grouped yet.
import type { RuntimeConfig } from '../../shared/types';

// ConfigView carries this meta key alongside the real settings; it is
// shown as a badge, never edited, so it is excluded from the table.
export type SettingKey = Exclude<keyof RuntimeConfig, 'restart_required'>;

export type SectionId =
  | 'supervisor'
  | 'concurrency'
  | 'coders-models'
  | 'worker-limits'
  | 'isolation-merge'
  | 'triage'
  | 'jobs'
  | 'compaction'
  | 'housekeeping'
  | 'integrations'
  | 'server'
  | 'notifications'
  | 'constants';

export type FieldKind =
  | 'text'
  | 'number'
  | 'boolean'
  | 'coder'
  | 'model'
  | 'isolation'
  | 'stall-action'
  | 'overrides'
  | 'context-windows'
  | 'cors';

export interface FieldDef {
  section: Exclude<SectionId, 'supervisor' | 'notifications' | 'constants'>;
  kind: FieldKind;
  label: string;
  help: string;
  placeholder?: string;
}

export const SECTIONS: { id: SectionId; title: string; blurb: string }[] = [
  { id: 'supervisor', title: 'Supervisor', blurb: 'Status, pause / resume / restart.' },
  { id: 'concurrency', title: 'Concurrency', blurb: 'How many workers run at once.' },
  { id: 'coders-models', title: 'Coders and models', blurb: 'Defaults, per-model context windows, installed coders.' },
  { id: 'worker-limits', title: 'Worker limits', blurb: 'Stall, attempt budget and context pressure.' },
  { id: 'isolation-merge', title: 'Isolation and merge', blurb: 'Worktrees and the post-merge hook.' },
  { id: 'triage', title: 'Triage', blurb: 'Blocked-task scans and observer caps.' },
  { id: 'jobs', title: 'Jobs', blurb: 'Approval gate and child defaults for job workers.' },
  { id: 'compaction', title: 'Compaction', blurb: 'Cheap-model memory compaction before continue launches.' },
  { id: 'housekeeping', title: 'Housekeeping', blurb: 'Retention of closed tasks and archives.' },
  { id: 'integrations', title: 'Integrations', blurb: 'Telegram, Ollama and Bedrock credentials.' },
  { id: 'server', title: 'Server', blurb: 'Bind address, port and CORS. Changes need a restart.' },
  { id: 'notifications', title: 'Browser notifications', blurb: 'Local toggles; stored in this browser only.' },
  { id: 'constants', title: 'Constants', blurb: 'Read-only code tunables with docs.' },
];

export const FIELD_DEFS: Record<SettingKey, FieldDef> = {
  max_concurrent: { section: 'concurrency', kind: 'number', label: 'Max concurrent', help: 'Agent subprocesses running at once.' },
  max_concurrent_overrides: { section: 'concurrency', kind: 'overrides', label: 'Per-coder limits', help: 'Coder:limit pairs; other coders use max concurrent.' },
  coder: { section: 'coders-models', kind: 'coder', label: 'Default coder', help: 'Coder CLI when a task sets no override.' },
  model: { section: 'coders-models', kind: 'model', label: 'Default model', help: 'Model when a task sets no override.' },
  context_windows: { section: 'coders-models', kind: 'context-windows', label: 'Per-model context windows', help: 'Model:tokens pairs; empty uses built-ins.' },
  opencode_default_model: { section: 'coders-models', kind: 'model', label: 'opencode default model', help: 'Ollama model for opencode tasks without an override.' },
  stall_warning_minutes: { section: 'worker-limits', kind: 'number', label: 'Stall warning (min)', help: 'Silence minutes before an attempt counts as stalled.' },
  stall_action: { section: 'worker-limits', kind: 'stall-action', label: 'Stall action', help: 'Warn logs only; kill stops the attempt.' },
  max_attempt_minutes: { section: 'worker-limits', kind: 'number', label: 'Max attempt (min)', help: 'Wall-clock cap per attempt; 0 disables.' },
  context_checkpoint_pct: { section: 'worker-limits', kind: 'number', label: 'Context checkpoint (%)', help: 'Peak-context percent that asks the model to wrap up early.' },
  context_kill_pct: { section: 'worker-limits', kind: 'number', label: 'Context kill (%)', help: 'Peak-context percent that kills with CONTEXT_PRESSURE.' },
  isolation: { section: 'isolation-merge', kind: 'isolation', label: 'Isolation', help: 'Worktree isolates repo tasks; none runs in place.' },
  isolation_exclude: { section: 'isolation-merge', kind: 'text', label: 'Isolation exclude', help: 'Repo roots that never get a worktree.', placeholder: '/Users/me/.ai' },
  post_merge_command: { section: 'isolation-merge', kind: 'text', label: 'Post-merge command', help: 'Shell command after a clean worktree merge; empty skips.', placeholder: 'make ui-build' },
  triage_interval_minutes: { section: 'triage', kind: 'number', label: 'Triage interval (min)', help: 'Minutes between blocked-task scans; 0 disables.' },
  observer_max_followups: { section: 'triage', kind: 'number', label: 'Observer max follow-ups', help: 'Follow-up tasks opened per observer validation round.' },
  observer_max_rounds: { section: 'triage', kind: 'number', label: 'Observer max rounds', help: 'Partial observer rounds before human review.' },
  job_gate: { section: 'jobs', kind: 'boolean', label: 'Job approval gate', help: 'Ask approval before a job spawns its planned children.' },
  job_child_coder: { section: 'jobs', kind: 'coder', label: 'Job child coder', help: 'Default coder for job-spawned child tasks.' },
  job_child_model: { section: 'jobs', kind: 'model', label: 'Job child model', help: 'Default model for job-spawned child tasks.' },
  job_max_children: { section: 'jobs', kind: 'number', label: 'Job max children', help: 'Max children one job phase may spawn.' },
  job_max_phase_attempts: { section: 'jobs', kind: 'number', label: 'Job max phase attempts', help: 'Research/design attempts before a job blocks.' },
  compaction_enabled: { section: 'compaction', kind: 'boolean', label: 'Compaction enabled', help: 'Compact before continue launches that need it; else truncate.' },
  compaction_coder: { section: 'compaction', kind: 'coder', label: 'Compaction coder', help: 'Coder CLI used for the cheap compaction call.' },
  compaction_model: { section: 'compaction', kind: 'model', label: 'Compaction model', help: 'Model used for the cheap compaction call.' },
  continue_pack_max_bytes: { section: 'compaction', kind: 'number', label: 'Continue pack budget (bytes)', help: 'Pack budget before a continue launch compacts.' },
  state_max_bytes: { section: 'compaction', kind: 'number', label: 'STATE.md cap (bytes)', help: 'Hard cap on the worker-memory file.' },
  gc_retention_days: { section: 'housekeeping', kind: 'number', label: 'Retention (days)', help: 'Days before closed tasks archive; 0 disables.' },
  gc_archive_days: { section: 'housekeeping', kind: 'number', label: 'Archive purge (days)', help: 'Days before archives delete permanently; 0 disables.' },
  telegram_chat_id: { section: 'integrations', kind: 'text', label: 'Telegram chat ID', help: 'Chat ID for notifications; empty disables them.' },
  telegram_allowed_ids: { section: 'integrations', kind: 'text', label: 'Telegram allowed sender IDs', help: 'Comma-separated; empty disables inbound commands.', placeholder: '123456789,987654321' },
  telegram_default_cwd: { section: 'integrations', kind: 'text', label: 'Telegram default directory', help: 'Working directory for tasks created via Telegram.' },
  opencode_ollama_url: { section: 'integrations', kind: 'text', label: 'Ollama API URL', help: 'Ollama API base URL used by the opencode coder.' },
  opencode_bedrock_region: { section: 'integrations', kind: 'text', label: 'Bedrock region', help: 'AWS region for Bedrock; empty inherits the environment.' },
  opencode_bedrock_profile: { section: 'integrations', kind: 'text', label: 'Bedrock profile', help: 'AWS profile for Bedrock; empty inherits the environment.' },
  ollama_ssh_host: { section: 'integrations', kind: 'text', label: 'Ollama SSH host', help: 'SSH host alias for the GPU box behind the Ollama URL.' },
  ollama_remote_port: { section: 'integrations', kind: 'number', label: 'Ollama remote port', help: 'Ollama port on the GPU box (remote end of the tunnel).' },
  serve_host: { section: 'server', kind: 'text', label: 'Bind address', help: '0.0.0.0 exposes LAN; 127.0.0.1 is local only.' },
  serve_port: { section: 'server', kind: 'number', label: 'Port', help: 'UI server port.' },
  serve_cors_origins: { section: 'server', kind: 'cors', label: 'CORS origins', help: 'Browser origins allowed cross-origin; empty is same-origin only.', placeholder: 'https://fleet.example.com' },
};

// Fields of one section, in table order.
export function fieldsFor(section: SectionId): SettingKey[] {
  return (Object.keys(FIELD_DEFS) as SettingKey[]).filter(
    key => FIELD_DEFS[key].section === section,
  );
}
